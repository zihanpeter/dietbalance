"""菜品（食堂）数据加载与处理。

数据源是仓库内 ``data/dishes.json``，由 ``scripts/build_dishes.py`` 从 Excel 表生成。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "dishes.json"

# 每克宏量素的能量（kcal）
KCAL_PER_GRAM_CARB = 4
KCAL_PER_GRAM_PROTEIN = 4
KCAL_PER_GRAM_FAT = 9


@dataclass(frozen=True)
class Dish:
    """单个菜品的展示模型。"""

    name: str
    kcal: int
    carb_pct: float
    protein_pct: float
    fat_pct: float
    features: str

    @property
    def carb_g(self) -> float:
        return round(self.kcal * self.carb_pct / 100 / KCAL_PER_GRAM_CARB, 1)

    @property
    def protein_g(self) -> float:
        return round(self.kcal * self.protein_pct / 100 / KCAL_PER_GRAM_PROTEIN, 1)

    @property
    def fat_g(self) -> float:
        return round(self.kcal * self.fat_pct / 100 / KCAL_PER_GRAM_FAT, 1)

    @property
    def calorie_level(self) -> str:
        """根据热量划分等级，用于前端筛选。"""
        if self.kcal < 100:
            return "low"
        if self.kcal < 200:
            return "mid"
        return "high"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["carb_g"] = self.carb_g
        data["protein_g"] = self.protein_g
        data["fat_g"] = self.fat_g
        data["calorie_level"] = self.calorie_level
        return data


@lru_cache(maxsize=1)
def load_dishes() -> list[Dish]:
    """读取并缓存 ``data/dishes.json``。"""
    if not DATA_PATH.exists():
        return []
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [
        Dish(
            name=str(item.get("name", "")).strip(),
            kcal=int(item.get("kcal", 0) or 0),
            carb_pct=float(item.get("carb_pct", 0) or 0),
            protein_pct=float(item.get("protein_pct", 0) or 0),
            fat_pct=float(item.get("fat_pct", 0) or 0),
            features=str(item.get("features", "")).strip(),
        )
        for item in raw
        if item.get("name")
    ]
