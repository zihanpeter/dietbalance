"""膳食方案：BMR / TDEE / 宏量目标计算 + 食堂菜品搭配推荐。

计算口径：

* BMR 采用 Mifflin-St Jeor 公式
* TDEE = BMR × 活动系数
* 目标热量与三大宏量素比例按减脂 / 保持 / 增肌三档调整
* 配餐默认「荤 + 素 + 主食」，覆盖碳水需求
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from heapq import heappush, heappushpop

from sources.dishes import Dish, load_dishes

KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_CARB = 4
KCAL_PER_G_FAT = 9


@dataclass(frozen=True)
class ActivityLevel:
    key: str
    label: str
    factor: float


ACTIVITY_LEVELS: tuple[ActivityLevel, ...] = (
    ActivityLevel("sedentary", "久坐 / 几乎不运动（考研、上课为主）", 1.2),
    ActivityLevel("light", "轻度活动（每周运动 1–3 次 / 校园常步行）", 1.375),
    ActivityLevel("moderate", "中度活动（每周运动 3–5 次）", 1.55),
    ActivityLevel("intense", "高强度运动（每天训练 / 体育生）", 1.725),
)


@dataclass(frozen=True)
class Goal:
    key: str
    label: str
    kcal_factor: float
    protein_per_kg: tuple[float, float]
    carb_share: tuple[float, float]
    note: str


GOALS: tuple[Goal, ...] = (
    Goal("fat_loss", "减脂", 0.8, (1.8, 2.0), (0.35, 0.40), "热量缺口 20%，高蛋白控碳水"),
    Goal("maintain", "保持", 1.0, (1.2, 1.5), (0.45, 0.50), "维持当前体重，均衡饮食"),
    Goal("muscle_gain", "增肌", 1.1, (1.6, 2.2), (0.50, 0.55), "热量盈余 10%，充足蛋白与碳水"),
)


@dataclass(frozen=True)
class Meal:
    key: str
    label: str
    ratio: float


MEALS: tuple[Meal, ...] = (
    Meal("breakfast", "早餐（约占全天 25%）", 0.25),
    Meal("lunch", "午餐（约占全天 40%）", 0.40),
    Meal("dinner", "晚餐（约占全天 35%）", 0.35),
)

ACTIVITY_BY_KEY = {a.key: a for a in ACTIVITY_LEVELS}
GOAL_BY_KEY = {g.key: g for g in GOALS}
MEAL_BY_KEY = {m.key: m for m in MEALS}

# 菜品角色分类
_VEGGIE_CATEGORIES = {"蔬菜类", "蔬菜类-综合", "蔬菜-肉炒", "菌菇类"}
_EXTRA_PROTEIN_CATEGORIES = {"蛋类", "豆制品"}
_STAPLE_CATEGORIES = {"主食-粥品", "主食-米饭"}
_COMPLETE_MEAL_KEYWORDS = (
    "套餐",
    "盖饭",
    "炒饭",
    "披萨",
    "汉堡",
    "堡",
    "焗饭",
    "拌面",
    "刀削面",
    "拉面",
    "米线",
    "意大利",
    "通心粉",
    "方便面",
    "卤面",
    "炒饼",
    "粉丝",
)


def calculate_bmr(gender: str, weight_kg: float, height_cm: float, age: int) -> float:
    """Mifflin-St Jeor 基础代谢率（kcal/天）。"""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if gender == "male" else base - 161


@dataclass(frozen=True)
class NutritionTarget:
    """一天的热量与宏量素目标。"""

    bmr: float
    activity: ActivityLevel
    tdee: float
    goal: Goal
    target_kcal: float
    protein_g: float
    protein_range: tuple[float, float]
    carb_g: float
    fat_g: float
    bmr_is_manual: bool

    @property
    def protein_kcal(self) -> float:
        return self.protein_g * KCAL_PER_G_PROTEIN

    @property
    def carb_kcal(self) -> float:
        return self.carb_g * KCAL_PER_G_CARB

    @property
    def fat_kcal(self) -> float:
        return self.fat_g * KCAL_PER_G_FAT


def build_target(
    *,
    gender: str,
    weight_kg: float,
    height_cm: float,
    age: int,
    activity_key: str,
    goal_key: str,
    manual_bmr: float | None = None,
) -> NutritionTarget:
    """由用户身体数据推导全天热量与宏量素目标。"""
    activity = ACTIVITY_BY_KEY[activity_key]
    goal = GOAL_BY_KEY[goal_key]

    bmr = manual_bmr if manual_bmr else calculate_bmr(gender, weight_kg, height_cm, age)
    tdee = bmr * activity.factor
    target_kcal = tdee * goal.kcal_factor

    protein_low = weight_kg * goal.protein_per_kg[0]
    protein_high = weight_kg * goal.protein_per_kg[1]
    protein_g = (protein_low + protein_high) / 2

    carb_share = sum(goal.carb_share) / 2
    carb_g = target_kcal * carb_share / KCAL_PER_G_CARB

    remaining_kcal = target_kcal - protein_g * KCAL_PER_G_PROTEIN - carb_g * KCAL_PER_G_CARB
    fat_g = max(remaining_kcal, target_kcal * 0.20) / KCAL_PER_G_FAT

    return NutritionTarget(
        bmr=bmr,
        activity=activity,
        tdee=tdee,
        goal=goal,
        target_kcal=target_kcal,
        protein_g=protein_g,
        protein_range=(protein_low, protein_high),
        carb_g=carb_g,
        fat_g=fat_g,
        bmr_is_manual=manual_bmr is not None,
    )


@dataclass(frozen=True)
class PlanDish:
    """搭配方案中的一道菜（按一份出品计）。"""

    name: str
    kcal: int
    portion_g: int | None
    category: str
    role: str  # "protein" | "veggie" | "carb"
    protein_g: float
    carb_g: float
    fat_g: float
    features: str


def _to_plan_dish(dish: Dish, role: str) -> PlanDish:
    total = float(dish.total_kcal or 0)
    return PlanDish(
        name=dish.name,
        kcal=int(dish.total_kcal or 0),
        portion_g=dish.portion_g,
        category=dish.category or "",
        role=role,
        protein_g=round(total * dish.protein_pct / 100 / KCAL_PER_G_PROTEIN, 1),
        carb_g=round(total * dish.carb_pct / 100 / KCAL_PER_G_CARB, 1),
        fat_g=round(total * dish.fat_pct / 100 / KCAL_PER_G_FAT, 1),
        features=dish.features,
    )


def _is_complete_meal(name: str, category: str) -> bool:
    if any(k in name for k in _COMPLETE_MEAL_KEYWORDS):
        return True
    return category.startswith("主食-") and category not in {
        "主食-粥品",
        "主食-米饭",
        "主食-面食",
    }


def _is_staple_side(dish: Dish) -> bool:
    """可与荤素搭配的「配菜主食」（非整餐套餐）。"""
    category = dish.category or ""
    name = dish.name
    if _is_complete_meal(name, category):
        return False
    if category in _STAPLE_CATEGORIES:
        return True
    if category == "主食-面食" and dish.carb_pct >= 45:
        return True
    if category.startswith("主食") and dish.carb_pct >= 50 and dish.protein_pct <= 22:
        return True
    return False


# 食堂常备基础主食（菜单未必单列）
_BUILTIN_STAPLES: tuple[PlanDish, ...] = (
    PlanDish(
        name="米饭",
        kcal=232,
        portion_g=200,
        category="主食-米饭",
        role="carb",
        protein_g=4.6,
        carb_g=49.0,
        fat_g=0.6,
        features="白米饭一份约 200 g，碳水主来源，配菜必备主食",
    ),
    PlanDish(
        name="馒头",
        kcal=221,
        portion_g=100,
        category="主食-面食",
        role="carb",
        protein_g=7.0,
        carb_g=47.0,
        fat_g=1.1,
        features="标准馒头约 100 g，方便携带的面食碳水",
    ),
)


@lru_cache(maxsize=1)
def _candidate_pools() -> tuple[list[PlanDish], list[PlanDish], list[PlanDish]]:
    """返回 (荤菜池, 素菜池, 主食池)，均按一份热量升序。"""
    proteins: list[PlanDish] = []
    veggies: list[PlanDish] = []
    staples: list[PlanDish] = list(_BUILTIN_STAPLES)

    for dish in load_dishes():
        if not dish.total_kcal:
            continue
        category = dish.category or ""
        if _is_staple_side(dish):
            staples.append(_to_plan_dish(dish, "carb"))
        elif category in _VEGGIE_CATEGORIES:
            veggies.append(_to_plan_dish(dish, "veggie"))
        elif category.startswith("肉类") or category in _EXTRA_PROTEIN_CATEGORIES:
            proteins.append(_to_plan_dish(dish, "protein"))

    proteins.sort(key=lambda d: d.kcal)
    veggies.sort(key=lambda d: d.kcal)
    staples.sort(key=lambda d: d.kcal)
    return proteins, veggies, staples


@dataclass
class MealPlan:
    """一套搭配方案（通常含荤 / 素 / 主食）。"""

    dishes: list[PlanDish]
    score: float = 0.0
    kcal: int = 0
    protein_g: float = 0.0
    carb_g: float = 0.0
    fat_g: float = 0.0
    kcal_diff: int = 0
    macro_shares: dict[str, float] = field(default_factory=dict)

    def finalize(self, meal_kcal: float) -> "MealPlan":
        self.kcal = sum(d.kcal for d in self.dishes)
        self.protein_g = round(sum(d.protein_g for d in self.dishes), 1)
        self.carb_g = round(sum(d.carb_g for d in self.dishes), 1)
        self.fat_g = round(sum(d.fat_g for d in self.dishes), 1)
        self.kcal_diff = int(round(self.kcal - meal_kcal))

        total = (
            self.protein_g * KCAL_PER_G_PROTEIN
            + self.carb_g * KCAL_PER_G_CARB
            + self.fat_g * KCAL_PER_G_FAT
        ) or 1
        self.macro_shares = {
            "protein": round(self.protein_g * KCAL_PER_G_PROTEIN / total * 100, 1),
            "carb": round(self.carb_g * KCAL_PER_G_CARB / total * 100, 1),
            "fat": round(self.fat_g * KCAL_PER_G_FAT / total * 100, 1),
        }
        # 展示顺序：荤 → 素 → 主食
        order = {"protein": 0, "veggie": 1, "carb": 2}
        self.dishes.sort(key=lambda d: order.get(d.role, 9))
        return self


# (热量, 蛋白 g, 脂肪 g, 碳水 g)
_Metrics = tuple[float, float, float, float]
_TOP_K = 500


@lru_cache(maxsize=1)
def _pool_metrics() -> tuple[list[_Metrics], list[_Metrics], list[_Metrics]]:
    proteins, veggies, staples = _candidate_pools()
    return (
        [(float(d.kcal), d.protein_g, d.fat_g, d.carb_g) for d in proteins],
        [(float(d.kcal), d.protein_g, d.fat_g, d.carb_g) for d in veggies],
        [(float(d.kcal), d.protein_g, d.fat_g, d.carb_g) for d in staples],
    )


def _fat_penalty_threshold(goal_key: str) -> tuple[float, float]:
    if goal_key == "fat_loss":
        return 0.30, 0.8
    if goal_key == "muscle_gain":
        return 0.40, 0.3
    return 0.35, 0.5


def _enumerate_combos(
    meal_kcal: float,
    meal_protein_g: float,
    meal_carb_g: float,
    goal_key: str,
    kcal_cap: float,
) -> list[tuple[float, tuple[tuple[str, int], ...]]]:
    """枚举搭配；组合以 ``(池名, 下标)`` 表示。"""
    protein_pool, veggie_pool, staple_pool = _pool_metrics()
    fat_threshold, fat_weight = _fat_penalty_threshold(goal_key)
    protein_weight = 0.55 if meal_protein_g > 0 else 0.0
    carb_weight = 0.55 if meal_carb_g > 0 else 0.0

    heap: list[tuple[float, int, tuple[tuple[str, int], ...]]] = []
    seq = 0

    def consider(
        kcal: float,
        protein: float,
        fat: float,
        carb: float,
        combo: tuple[tuple[str, int], ...],
        *,
        has_staple: bool,
    ) -> None:
        nonlocal seq
        penalty = abs(kcal - meal_kcal) / meal_kcal
        if kcal > meal_kcal:
            penalty *= 1.3
        if protein_weight and protein < meal_protein_g:
            penalty += protein_weight * (meal_protein_g - protein) / meal_protein_g
        if carb_weight and carb < meal_carb_g:
            penalty += carb_weight * (meal_carb_g - carb) / meal_carb_g
        # 碳水明显超标时（减脂）略微惩罚
        if goal_key == "fat_loss" and meal_carb_g > 0 and carb > meal_carb_g * 1.25:
            penalty += 0.25 * (carb - meal_carb_g) / meal_carb_g
        fat_share = fat * KCAL_PER_G_FAT / kcal if kcal else 0.0
        if fat_share > fat_threshold:
            penalty += fat_weight * (fat_share - fat_threshold)
        if not has_staple:
            penalty += 0.35  # 缺少主食的方案降权

        seq += 1
        item = (-penalty, seq, combo)
        if len(heap) < _TOP_K:
            heappush(heap, item)
        elif penalty < -heap[0][0]:
            heappushpop(heap, item)

    # 主路径：荤 + 素 + 主食
    for pi, (pk, pp, pf, pc) in enumerate(protein_pool):
        if pk > kcal_cap:
            break
        for vi, (vk, vp, vf, vc) in enumerate(veggie_pool):
            k2 = pk + vk
            if k2 > kcal_cap:
                break
            for si, (sk, sp, sf, sc) in enumerate(staple_pool):
                k3 = k2 + sk
                if k3 > kcal_cap:
                    break
                consider(
                    k3,
                    pp + vp + sp,
                    pf + vf + sf,
                    pc + vc + sc,
                    (("p", pi), ("v", vi), ("s", si)),
                    has_staple=True,
                )

    # 荤 + 主食（素菜装不下时）
    for pi, (pk, pp, pf, pc) in enumerate(protein_pool):
        if pk > kcal_cap:
            break
        for si, (sk, sp, sf, sc) in enumerate(staple_pool):
            k2 = pk + sk
            if k2 > kcal_cap:
                break
            consider(
                k2,
                pp + sp,
                pf + sf,
                pc + sc,
                (("p", pi), ("s", si)),
                has_staple=True,
            )

    # 荤 + 素 + 素（无主食，仅作兜底）
    for pi, (pk, pp, pf, pc) in enumerate(protein_pool):
        if pk > kcal_cap:
            break
        for vi, (v1k, v1p, v1f, v1c) in enumerate(veggie_pool):
            k2 = pk + v1k
            if k2 > kcal_cap:
                break
            for vj in range(vi + 1, len(veggie_pool)):
                v2k, v2p, v2f, v2c = veggie_pool[vj]
                k3 = k2 + v2k
                if k3 > kcal_cap:
                    break
                consider(
                    k3,
                    pp + v1p + v2p,
                    pf + v1f + v2f,
                    pc + v1c + v2c,
                    (("p", pi), ("v", vi), ("v", vj)),
                    has_staple=False,
                )

    # 荤 + 荤 + 主食（高蛋白需求）
    for pi, (p1k, p1p, p1f, p1c) in enumerate(protein_pool):
        if p1k > kcal_cap:
            break
        for pj in range(pi + 1, len(protein_pool)):
            p2k, p2p, p2f, p2c = protein_pool[pj]
            k2 = p1k + p2k
            if k2 > kcal_cap:
                break
            for si, (sk, sp, sf, sc) in enumerate(staple_pool):
                k3 = k2 + sk
                if k3 > kcal_cap:
                    break
                consider(
                    k3,
                    p1p + p2p + sp,
                    p1f + p2f + sf,
                    p1c + p2c + sc,
                    (("p", pi), ("p", pj), ("s", si)),
                    has_staple=True,
                )

    return sorted(((-neg, combo) for neg, _, combo in heap), key=lambda item: item[0])


def build_plans(
    meal_kcal: float,
    meal_protein_g: float,
    goal_key: str,
    meal_carb_g: float = 0.0,
    limit: int = 3,
) -> list[MealPlan]:
    """挑选 ``limit`` 套互不重复用菜的搭配方案（默认含主食）。"""
    if meal_kcal <= 0:
        return []

    scored = _enumerate_combos(
        meal_kcal, meal_protein_g, meal_carb_g, goal_key, meal_kcal * 1.35
    )
    if len(scored) < limit:
        scored = _enumerate_combos(
            meal_kcal, meal_protein_g, meal_carb_g, goal_key, float("inf")
        )

    proteins, veggies, staples = _candidate_pools()
    pools = {"p": proteins, "v": veggies, "s": staples}

    plans: list[MealPlan] = []
    used: set[str] = set()
    for score, combo in scored:
        dishes = [pools[pool][idx] for pool, idx in combo]
        names = {d.name for d in dishes}
        # 内置主食可在多套方案中复用；其余菜不重复
        unique_names = {n for n in names if n not in {"米饭", "馒头"}}
        if unique_names & used:
            continue
        plans.append(
            MealPlan(dishes=dishes, score=round(score, 4)).finalize(meal_kcal)
        )
        used |= unique_names
        if len(plans) >= limit:
            break

    return plans
