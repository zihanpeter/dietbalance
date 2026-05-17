"""USDA FoodData Central 数据源。

官方文档：https://fdc.nal.usda.gov/api-guide
申请免费 API Key：https://fdc.nal.usda.gov/api-key-signup
未在项目根目录 .env 中设置 USDA_API_KEY 时使用 DEMO_KEY（30 次/IP/小时）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from . import cache
from .models import FoodItem, NutritionFact

SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
REQUEST_TIMEOUT = 10
USER_AGENT = "DietBalance/0.1"
ENV_FILE_PATH = Path(__file__).resolve().parent.parent / ".env"

# USDA nutrientId -> (中文标签, 单位, 换算系数)
# USDA 中 sodium 是 mg，我们统一用 g。
NUTRIENT_MAP: dict[int, tuple[str, str, float]] = {
    1008: ("能量", "kcal", 1.0),             # Energy
    1003: ("蛋白质", "g", 1.0),                # Protein
    1004: ("脂肪", "g", 1.0),                  # Total lipid (fat)
    1258: ("— 饱和脂肪", "g", 1.0),            # Fatty acids, total saturated
    1005: ("碳水化合物", "g", 1.0),            # Carbohydrate, by difference
    2000: ("— 糖", "g", 1.0),                  # Sugars, total
    1079: ("膳食纤维", "g", 1.0),              # Fiber, total dietary
    1093: ("钠", "g", 0.001),                  # Sodium, Na (mg -> g)
    1087: ("钙", "g", 0.001),                  # Calcium, Ca (mg -> g)
    1089: ("铁", "g", 0.001),                  # Iron, Fe (mg -> g)
    1162: ("维生素 C", "mg", 1.0),             # Vitamin C
}

# 展示顺序
DISPLAY_ORDER = [1008, 1003, 1004, 1258, 1005, 2000, 1079, 1093, 1087, 1089, 1162]


def _read_key_from_env_file(file_path: Path) -> str:
    """从 .env 风格文件读取 USDA_API_KEY，读取失败时返回空字符串。"""
    if not file_path.exists() or not file_path.is_file():
        return ""

    try:
        for raw_line in file_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() != "USDA_API_KEY":
                continue
            cleaned = value.strip().strip('"').strip("'")
            if cleaned:
                return cleaned
    except OSError:
        return ""
    return ""


def _api_key() -> str:
    key_from_file = _read_key_from_env_file(ENV_FILE_PATH)
    if key_from_file:
        return key_from_file
    return "DEMO_KEY"


def _parse_food(food: dict[str, Any]) -> FoodItem:
    nutrients_by_id: dict[int, float] = {}
    for n in food.get("foodNutrients") or []:
        nid = n.get("nutrientId")
        value = n.get("value")
        if nid is None or value is None:
            continue
        try:
            nutrients_by_id[int(nid)] = float(value)
        except (TypeError, ValueError):
            continue

    nutrition: list[NutritionFact] = []
    for nid in DISPLAY_ORDER:
        if nid not in NUTRIENT_MAP:
            continue
        label, unit, factor = NUTRIENT_MAP[nid]
        raw = nutrients_by_id.get(nid)
        value = raw * factor if raw is not None else None
        nutrition.append(NutritionFact(label=label, value=value, unit=unit))

    description = str(food.get("description") or "未知食品").strip()
    data_type = str(food.get("dataType") or "").strip()
    brand = str(food.get("brandOwner") or food.get("brandName") or "").strip()

    fdc_id = food.get("fdcId", "")
    source_url = (
        f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients" if fdc_id else ""
    )

    return FoodItem(
        name=description,
        brand=brand,
        image_url="",
        quantity="",
        categories=data_type,
        source_url=source_url,
        nutriscore="",
        source="USDA",
        nutrition_per_100g=nutrition,
    )


def _relevance_score(name: str, query: str) -> int:
    """让"原料 / raw"类条目排得更靠前，支持多词查询。"""
    lower = name.lower()
    tokens = [t for t in query.lower().split() if t]
    if not tokens:
        return 0

    primary = tokens[0].rstrip("s")
    first = lower.split(",", 1)[0].rstrip("s").strip()

    score = 0
    if first == primary:
        score += 100
    elif first.startswith(primary):
        score += 50

    for t in tokens[1:]:
        if t in lower:
            score += 15

    if ", raw" in lower or lower.endswith(" raw"):
        score += 30

    for penalty_kw in ("babyfood", "snacks", "candies", "beverages"):
        if penalty_kw in lower:
            score -= 20
    return score


def _fetch_foods(query: str, page_size: int) -> list[dict[str, Any]]:
    """调用 USDA API（带磁盘缓存）。"""
    cache_key = f"{query}|{page_size}|Foundation+SR"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "api_key": _api_key(),
        "query": query,
        "pageSize": page_size,
        "dataType": "Foundation,SR Legacy",
    }
    resp = requests.get(
        SEARCH_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    foods = data.get("foods", []) or []
    cache.set_(cache_key, foods)
    return foods


def search(query: str, page_size: int = 6) -> list[FoodItem]:
    query = (query or "").strip()
    if not query:
        return []

    fetch_size = max(page_size, 15)
    foods = _fetch_foods(query, fetch_size)

    items = [_parse_food(f) for f in foods]
    items = [item for item in items if item.has_nutrition]
    items.sort(key=lambda it: _relevance_score(it.name, query), reverse=True)
    return items[:page_size]
