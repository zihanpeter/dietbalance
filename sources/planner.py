"""膳食方案：BMR / TDEE / 宏量目标计算 + 食堂菜品搭配推荐。

计算口径：

* BMR 采用 Mifflin-St Jeor 公式
* TDEE = BMR × 活动系数
* 目标热量与三大宏量素比例按减脂 / 保持 / 增肌三档调整
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

# 菜品在搭配中承担的角色
_VEGGIE_CATEGORIES = {"蔬菜类", "蔬菜类-综合", "蔬菜-肉炒", "菌菇类"}
_EXTRA_PROTEIN_CATEGORIES = {"蛋类", "豆制品"}


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

    # 脂肪吃掉剩余热量，并保证不低于总热量的 20%（健康下限）
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
    role: str  # "protein" | "veggie"
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


@lru_cache(maxsize=1)
def _candidate_pools() -> tuple[list[PlanDish], list[PlanDish]]:
    """返回 (荤菜池, 素菜池)，均按一份热量升序排列。"""
    proteins: list[PlanDish] = []
    veggies: list[PlanDish] = []

    for dish in load_dishes():
        if not dish.total_kcal:
            continue
        category = dish.category or ""
        if category in _VEGGIE_CATEGORIES:
            veggies.append(_to_plan_dish(dish, "veggie"))
        elif category.startswith("肉类") or category in _EXTRA_PROTEIN_CATEGORIES:
            proteins.append(_to_plan_dish(dish, "protein"))

    proteins.sort(key=lambda d: d.kcal)
    veggies.sort(key=lambda d: d.kcal)
    return proteins, veggies


@dataclass
class MealPlan:
    """一套 2–3 道菜的搭配方案。"""

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
        return self


# 候选组合的中间表示：(热量, 蛋白 g, 脂肪 g)
_Metrics = tuple[float, float, float]

# 组合枚举时保留的候选数量，足够在去重后凑满方案
_TOP_K = 400


@lru_cache(maxsize=1)
def _pool_metrics() -> tuple[list[_Metrics], list[_Metrics]]:
    proteins, veggies = _candidate_pools()
    to_metrics = [(float(d.kcal), d.protein_g, d.fat_g) for d in proteins]
    veg_metrics = [(float(d.kcal), d.protein_g, d.fat_g) for d in veggies]
    return to_metrics, veg_metrics


def _fat_penalty_threshold(goal_key: str) -> tuple[float, float]:
    """返回 (脂肪供能比阈值, 惩罚权重)。"""
    if goal_key == "fat_loss":
        return 0.30, 0.8
    if goal_key == "muscle_gain":
        return 0.40, 0.3
    return 0.35, 0.5


def _enumerate_combos(
    meal_kcal: float,
    meal_protein_g: float,
    goal_key: str,
    kcal_cap: float,
) -> list[tuple[float, tuple[tuple[str, int], ...]]]:
    """枚举搭配并返回得分最低（最贴合目标）的若干组合。

    组合以 ``(池名, 下标)`` 表示，避免在热循环里构造对象。
    """
    protein_pool, veggie_pool = _pool_metrics()
    fat_threshold, fat_weight = _fat_penalty_threshold(goal_key)
    protein_weight = 0.6 if meal_protein_g > 0 else 0.0

    # 以 (-score, seq, combo) 入堆，堆顶恒为当前最差候选，便于淘汰
    heap: list[tuple[float, int, tuple[tuple[str, int], ...]]] = []
    seq = 0

    def consider(kcal: float, protein: float, fat: float, combo: tuple[tuple[str, int], ...]) -> None:
        nonlocal seq
        penalty = abs(kcal - meal_kcal) / meal_kcal
        if kcal > meal_kcal:
            penalty *= 1.3
        if protein_weight and protein < meal_protein_g:
            penalty += protein_weight * (meal_protein_g - protein) / meal_protein_g
        fat_share = fat * KCAL_PER_G_FAT / kcal if kcal else 0.0
        if fat_share > fat_threshold:
            penalty += fat_weight * (fat_share - fat_threshold)

        seq += 1
        item = (-penalty, seq, combo)
        if len(heap) < _TOP_K:
            heappush(heap, item)
        elif penalty < -heap[0][0]:
            heappushpop(heap, item)

    for pi, (pk, pp, pf) in enumerate(protein_pool):
        if pk > kcal_cap:
            break
        for vi, (v1k, v1p, v1f) in enumerate(veggie_pool):
            k2 = pk + v1k
            if k2 > kcal_cap:
                break
            consider(k2, pp + v1p, pf + v1f, (("p", pi), ("v", vi)))
            # 荤 + 素 + 素
            for vj in range(vi + 1, len(veggie_pool)):
                v2k, v2p, v2f = veggie_pool[vj]
                k3 = k2 + v2k
                if k3 > kcal_cap:
                    break
                consider(k3, pp + v1p + v2p, pf + v1f + v2f, (("p", pi), ("v", vi), ("v", vj)))

    # 荤 + 荤 + 素（蛋白需求较高时更容易命中）
    for pi, (p1k, p1p, p1f) in enumerate(protein_pool):
        if p1k > kcal_cap:
            break
        for pj in range(pi + 1, len(protein_pool)):
            p2k, p2p, p2f = protein_pool[pj]
            k2 = p1k + p2k
            if k2 > kcal_cap:
                break
            for vi, (vk, vp, vf) in enumerate(veggie_pool):
                k3 = k2 + vk
                if k3 > kcal_cap:
                    break
                consider(k3, p1p + p2p + vp, p1f + p2f + vf, (("p", pi), ("p", pj), ("v", vi)))

    return sorted(((-neg, combo) for neg, _, combo in heap), key=lambda item: item[0])


def build_plans(
    meal_kcal: float,
    meal_protein_g: float,
    goal_key: str,
    limit: int = 3,
) -> list[MealPlan]:
    """挑选 ``limit`` 套互不重复用菜的搭配方案。"""
    if meal_kcal <= 0:
        return []

    scored = _enumerate_combos(meal_kcal, meal_protein_g, goal_key, meal_kcal * 1.35)
    if len(scored) < limit:
        # 目标热量很低时放宽上限，至少给出可选项
        scored = _enumerate_combos(meal_kcal, meal_protein_g, goal_key, float("inf"))

    proteins, veggies = _candidate_pools()
    pools = {"p": proteins, "v": veggies}

    plans: list[MealPlan] = []
    used: set[str] = set()
    for score, combo in scored:
        dishes = [pools[pool][idx] for pool, idx in combo]
        names = {d.name for d in dishes}
        if names & used:
            continue
        plans.append(MealPlan(dishes=dishes, score=round(score, 4)).finalize(meal_kcal))
        used |= names
        if len(plans) >= limit:
            break

    return plans
