"""极简 JSON 文件缓存。

用于缓存 USDA 接口返回，减少对有限额 DEMO_KEY 的调用。
读写失败（如目录无写权限）会被吞掉，不影响主流程。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_FILE = CACHE_DIR / "usda.json"
DEFAULT_TTL_SEC = 7 * 24 * 3600

_lock = Lock()
_writable: bool | None = None


def _ensure_writable() -> bool:
    """探测缓存目录是否可写；结果缓存，避免每次请求都重试 mkdir。"""
    global _writable
    if _writable is not None:
        return _writable
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        probe = CACHE_DIR / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        _writable = True
    except OSError:
        _writable = False
    return _writable


def _load() -> dict[str, dict[str, Any]]:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    if not _ensure_writable():
        return
    try:
        tmp = CACHE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_FILE)
    except OSError:
        # 缓存失败不应拖垮搜索
        global _writable
        _writable = False


def get(key: str, ttl_sec: int = DEFAULT_TTL_SEC) -> Any | None:
    with _lock:
        data = _load()
        entry = data.get(key)
        if not entry:
            return None
        if time.time() - entry.get("ts", 0) > ttl_sec:
            return None
        return entry.get("value")


def set_(key: str, value: Any) -> None:
    with _lock:
        data = _load()
        data[key] = {"ts": time.time(), "value": value}
        _save(data)
