"""跨数据源的统一数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NutritionFact:
    """单位：每 100 g / 100 ml。"""

    label: str
    value: float | None
    unit: str


@dataclass
class FoodItem:
    name: str
    brand: str = ""
    image_url: str = ""
    quantity: str = ""
    categories: str = ""
    source_url: str = ""
    nutriscore: str = ""
    source: str = ""  # 数据来源（USDA / OpenFoodFacts）
    nutrition_per_100g: list[NutritionFact] = field(default_factory=list)

    @property
    def has_nutrition(self) -> bool:
        return any(n.value is not None for n in self.nutrition_per_100g)
