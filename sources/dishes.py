"""菜品（食堂）数据加载与处理。

数据源是仓库内 ``data/dishes.json``，由楼层菜单构建脚本生成：
``scripts/build_from_floor_menus.py``。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
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
    total_kcal: int | None = None  # 一份/一碗总热量
    portion_g: int | None = None  # 出品重量（克）
    category: str | None = None  # 菜品类别，如「肉类-鸡肉」「蔬菜类」
    floors: tuple[str, ...] = field(default_factory=tuple)  # 出现楼层

    @property
    def has_macros(self) -> bool:
        return bool(self.carb_pct or self.protein_pct or self.fat_pct)

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
        """根据每 100 g 热量划分等级，用于前端筛选。"""
        if self.kcal <= 0:
            return "unknown"
        if self.kcal < 100:
            return "low"
        if self.kcal < 200:
            return "mid"
        return "high"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["floors"] = list(self.floors)
        data["has_macros"] = self.has_macros
        data["carb_g"] = self.carb_g
        data["protein_g"] = self.protein_g
        data["fat_g"] = self.fat_g
        data["calorie_level"] = self.calorie_level
        return data


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _parse_floors(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(x).strip() for x in value if str(x).strip())
    return (str(value).strip(),)


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
            total_kcal=_optional_int(item.get("total_kcal")),
            portion_g=_optional_int(item.get("portion_g")),
            category=(str(item["category"]).strip() if item.get("category") else None),
            floors=_parse_floors(item.get("floors")),
        )
        for item in raw
        if item.get("name")
    ]
