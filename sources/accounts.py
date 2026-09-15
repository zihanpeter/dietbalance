"""用户账号与身体档案（SQLite）。

数据库默认落在 ``.cache/accounts.db``（与浏览量缓存同目录，需可写）。
密码使用 Werkzeug 的 scrypt/pbkdf2 哈希，会话仅存 user_id。
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).resolve().parent.parent / ".cache" / "accounts.db"

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{2,24}$")
_lock = Lock()

PROFILE_KEYS = ("gender", "age", "height", "weight", "activity", "goal", "meal", "bmr")


@dataclass
class User:
    id: int
    username: str
    profile: dict[str, str]

    def profile_for_form(self) -> dict[str, str]:
        """返回配餐表单可用的字段（缺省给空字符串）。"""
        out = {k: "" for k in PROFILE_KEYS}
        for key in PROFILE_KEYS:
            value = self.profile.get(key)
            if value is None:
                continue
            out[key] = str(value)
        if out["gender"] not in {"male", "female"}:
            out["gender"] = "male"
        if not out["activity"]:
            out["activity"] = "light"
        if not out["goal"]:
            out["goal"] = "fat_loss"
        if not out["meal"]:
            out["meal"] = "lunch"
        return out


class AccountError(Exception):
    """用户可见的账号错误。"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    try:
        with _lock:
            conn = _connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        password_hash TEXT NOT NULL,
                        profile_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()
    except OSError as exc:
        # 目录不可写时延迟到首次真正读写再失败，避免拖垮整个站点启动
        raise AccountError(f"无法初始化账号数据库：{exc}") from exc


def validate_username(username: str) -> str:
    name = (username or "").strip()
    if not _USERNAME_RE.match(name):
        raise AccountError("用户名需为 2–24 个字符（中文 / 字母 / 数字 / 下划线）")
    return name


def validate_password(password: str) -> str:
    if not password or len(password) < 6:
        raise AccountError("密码至少 6 位")
    if len(password) > 72:
        raise AccountError("密码过长")
    return password


def register(username: str, password: str) -> User:
    name = validate_username(username)
    pwd = validate_password(password)
    now = datetime.now(timezone.utc).isoformat()
    password_hash = generate_password_hash(pwd)

    with _lock:
        conn = _connect()
        try:
            try:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash, profile_json, created_at) "
                    "VALUES (?, ?, '{}', ?)",
                    (name, password_hash, now),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise AccountError("该用户名已被注册") from exc
            return User(id=int(cur.lastrowid), username=name, profile={})
        finally:
            conn.close()


def authenticate(username: str, password: str) -> User:
    name = (username or "").strip()
    if not name or not password:
        raise AccountError("请输入用户名和密码")

    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, username, password_hash, profile_json FROM users "
                "WHERE username = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
        finally:
            conn.close()

    if row is None or not check_password_hash(row["password_hash"], password):
        raise AccountError("用户名或密码错误")
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        profile=_parse_profile(row["profile_json"]),
    )


def get_user(user_id: int) -> User | None:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, username, profile_json FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        return None
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        profile=_parse_profile(row["profile_json"]),
    )


def save_profile(user_id: int, profile: dict[str, str]) -> User:
    cleaned = {k: str(profile.get(k, "") or "").strip() for k in PROFILE_KEYS}
    payload = json.dumps(cleaned, ensure_ascii=False)

    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE users SET profile_json = ? WHERE id = ?",
                (payload, int(user_id)),
            )
            if cur.rowcount == 0:
                raise AccountError("账号不存在")
            conn.commit()
            row = conn.execute(
                "SELECT id, username, profile_json FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
        finally:
            conn.close()

    assert row is not None
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        profile=_parse_profile(row["profile_json"]),
    )


def _parse_profile(raw: object) -> dict[str, str]:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def user_to_dict(user: User) -> dict:
    return asdict(user)
