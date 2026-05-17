"""Open Food Facts 数据源（用于包装商品）。"""
from __future__ import annotations

from typing import Any

import requests

from .models import FoodItem, NutritionFact

SEARCH_URL_V3 = "https://search.openfoodfacts.org/search"
SEARCH_URL_LEGACY = "https://world.openfoodfacts.org/cgi/search.pl"
REQUEST_TIMEOUT = 10
USER_AGENT = "DietBalance/0.1 (https://example.com)"

FIELDS = [
    "code",
    "product_name",
    "product_name_zh",
    "generic_name",
    "brands",
    "quantity",
    "categories",
    "image_front_small_url",
    "image_url",
    "nutriscore_grade",
    "nutriments",
]


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any, sep: str = ", ") -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return sep.join(str(v) for v in value if v).strip()
    return str(value).strip()


def _parse_product(product: dict[str, Any]) -> FoodItem:
    nutriments = product.get("nutriments", {}) or {}

    def n(key: str) -> float | None:
        return _float_or_none(nutriments.get(f"{key}_100g"))

    nutrition = [
        NutritionFact("能量", n("energy-kcal"), "kcal"),
        NutritionFact("蛋白质", n("proteins"), "g"),
        NutritionFact("脂肪", n("fat"), "g"),
        NutritionFact("— 饱和脂肪", n("saturated-fat"), "g"),
        NutritionFact("碳水化合物", n("carbohydrates"), "g"),
        NutritionFact("— 糖", n("sugars"), "g"),
        NutritionFact("膳食纤维", n("fiber"), "g"),
        NutritionFact("钠", n("sodium"), "g"),
        NutritionFact("盐", n("salt"), "g"),
    ]

    name = (
        _as_str(product.get("product_name_zh"))
        or _as_str(product.get("product_name"))
        or _as_str(product.get("generic_name"))
        or "未知食品"
    )

    code = _as_str(product.get("code"))
    source_url = f"https://world.openfoodfacts.org/product/{code}" if code else ""

    return FoodItem(
        name=name,
        brand=_as_str(product.get("brands")),
        image_url=_as_str(product.get("image_front_small_url"))
        or _as_str(product.get("image_url")),
        quantity=_as_str(product.get("quantity")),
        categories=_as_str(product.get("categories")),
        source_url=source_url,
        nutriscore=_as_str(product.get("nutriscore_grade")).upper(),
        source="OpenFoodFacts",
        nutrition_per_100g=nutrition,
    )


def _search_v3(query: str, page_size: int) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "page_size": page_size,
        "fields": ",".join(FIELDS),
    }
    resp = requests.get(
        SEARCH_URL_V3,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("hits", []) or []


def _search_legacy(query: str, page_size: int) -> list[dict[str, Any]]:
    params = {
        "search_terms": query,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": page_size,
        "fields": ",".join(FIELDS),
    }
    resp = requests.get(
        SEARCH_URL_LEGACY,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("products", []) or []


def search(query: str, page_size: int = 6) -> list[FoodItem]:
    query = (query or "").strip()
    if not query:
        return []

    products: list[dict[str, Any]] = []
    last_exc: Exception | None = None
    for strategy in (_search_v3, _search_legacy):
        try:
            products = strategy(query, page_size)
            break
        except requests.RequestException as exc:
            last_exc = exc
            continue

    if not products and last_exc is not None:
        raise RuntimeError(str(last_exc))

    items = [_parse_product(p) for p in products]
    items_with_nutri = [item for item in items if item.has_nutrition]
    return items_with_nutri or items
