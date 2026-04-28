"""食品搜索编排器。

策略：
1. 若输入是中文，先走中英映射字典翻译成英文
2. 优先查 USDA（原始食材、生鲜、家常食物）
3. 若 USDA 无结果 / 报错，再查 Open Food Facts（包装商品）
4. 返回 (items, notice) —— notice 用于在 UI 展示"USDA 限额用尽，已回落 OFF"之类的提示
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

from sources import openfoodfacts, usda
from sources.models import FoodItem, NutritionFact
from sources.translate import has_chinese, to_english

__all__ = ["FoodItem", "NutritionFact", "SearchResult", "search_food"]


@dataclass
class SearchResult:
    items: list[FoodItem]
    notice: str = ""  # 非致命提示（如 USDA 限额）


def _describe_http_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        if code == 429:
            return (
                "USDA API 今日限额已用完（DEMO_KEY 每 IP 每小时 30 次）。"
                "请到 https://fdc.nal.usda.gov/api-key-signup 免费申请 key，"
                "然后设置环境变量 USDA_API_KEY 后重启程序。"
            )
        if code in (401, 403):
            return "USDA API Key 无效，请检查 USDA_API_KEY 环境变量。"
    return ""


def search_food(query: str, page_size: int = 8) -> SearchResult:
    query = (query or "").strip()
    if not query:
        return SearchResult(items=[])

    notice = ""
    usda_error: Exception | None = None
    items: list[FoodItem] = []

    usda_query = to_english(query) if has_chinese(query) else query
    try:
        items = usda.search(usda_query, page_size=page_size)
    except Exception as exc:
        usda_error = exc

    if not items:
        try:
            off_items = openfoodfacts.search(query, page_size=page_size)
        except Exception as off_exc:
            off_items = []
            if usda_error is None:
                raise RuntimeError(f"搜索失败: {off_exc}") from off_exc

        items = off_items

        if usda_error is not None:
            detail = _describe_http_error(usda_error) or str(usda_error)
            if items:
                notice = f"USDA 查询失败，已回落到 Open Food Facts。{detail}"
            else:
                raise RuntimeError(f"搜索失败: {detail}") from usda_error

    return SearchResult(items=items, notice=notice)
