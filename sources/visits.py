"""站点浏览量计数（JSON 文件持久化）。

存储在 ``.cache/visits.json``；读写失败时静默降级，不影响页面渲染。
多 worker 下偶发计数丢失可接受，对小站足够。
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
VISITS_FILE = CACHE_DIR / "visits.json"

_lock = Lock()
_writable: bool | None = None


def _ensure_writable() -> bool:
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


def _load() -> dict[str, int]:
    if not VISITS_FILE.exists():
        return {"total": 0}
    try:
        raw = json.loads(VISITS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"total": 0}
    if not isinstance(raw, dict):
        return {"total": 0}
    result: dict[str, int] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    result.setdefault("total", 0)
    return result


def _save(data: dict[str, int]) -> None:
    if not _ensure_writable():
        return
    try:
        tmp = VISITS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(VISITS_FILE)
    except OSError:
        global _writable
        _writable = False


def increment(path: str = "/") -> int:
    """页面访问 +1，返回更新后的全站总浏览量。"""
    key = path.split("?", 1)[0] or "/"
    with _lock:
        data = _load()
        data["total"] = int(data.get("total", 0)) + 1
        data[key] = int(data.get(key, 0)) + 1
        _save(data)
        return data["total"]


def total() -> int:
    """读取全站总浏览量（不递增）。"""
    with _lock:
        return int(_load().get("total", 0))
