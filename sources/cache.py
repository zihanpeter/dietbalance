"""极简 JSON 文件缓存。

用于缓存 USDA 接口返回，减少对有限额 DEMO_KEY 的调用。
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


def _load() -> dict[str, dict[str, Any]]:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_FILE)


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
