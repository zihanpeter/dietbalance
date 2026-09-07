import os
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from food_api import search_food
from sources.dishes import load_dishes
from sources.planner import (
    ACTIVITY_BY_KEY,
    ACTIVITY_LEVELS,
    GOAL_BY_KEY,
    GOALS,
    MEAL_BY_KEY,
    MEALS,
    build_plans,
    build_target,
)

app = Flask(__name__)
app.config["PREFERRED_URL_SCHEME"] = os.environ.get("PREFERRED_URL_SCHEME", "https")


@app.context_processor
def _inject_static_versioner():
    """提供 ``versioned_static(filename)``：以静态文件 mtime 作为版本号，
    避免修改 CSS / JS 后被 Cloudflare 或浏览器缓存咬住。"""
    static_root = Path(app.static_folder or "static")

    def versioned_static(filename: str) -> str:
        url = url_for("static", filename=filename)
        try:
            mtime = int((static_root / filename).stat().st_mtime)
        except OSError:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}v={mtime}"

    return {"versioned_static": versioned_static}

# 反向代理层数：默认 1（即直接由 Cloudflare / Nginx / PaaS 前代理）。
# 若链路是 Cloudflare → Nginx → app，则设为 2，以此类推。
_proxy_hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=_proxy_hops,
    x_proto=_proxy_hops,
    x_host=_proxy_hops,
    x_prefix=_proxy_hops,
)


@app.route("/", methods=["GET"])
def index() -> str:
    """封面 / 落地页。"""
    return render_template(
        "landing.html",
        app_name="DietBalance",
        year=datetime.now().year,
    )


@app.route("/search", methods=["GET"])
def search() -> str:
    """食品营养查询页。"""
    query = (request.args.get("q") or "").strip()
    results = []
    error = ""
    notice = ""

    if query:
        try:
            result = search_food(query)
            results = result.items
            notice = result.notice
        except RuntimeError as exc:
            error = str(exc)

    return render_template(
        "index.html",
        app_name="DietBalance",
        year=datetime.now().year,
        query=query,
        results=results,
        error=error,
        notice=notice,
        searched=bool(query),
    )


@app.route("/dishes", methods=["GET"])
def dishes() -> str:
    """食堂菜品营养热量查询页面。"""
    dish_list = [d.to_dict() for d in load_dishes()]
    return render_template(
        "dishes.html",
        app_name="DietBalance",
        year=datetime.now().year,
        dishes=dish_list,
    )


def _parse_number(
    raw: str,
    label: str,
    low: float,
    high: float,
    errors: list[str],
    *,
    required: bool = True,
) -> float | None:
    """解析并校验表单里的数值输入，出错时把提示写入 ``errors``。"""
    raw = (raw or "").strip()
    if not raw:
        if required:
            errors.append(f"请填写{label}")
        return None
    try:
        value = float(raw)
    except ValueError:
        errors.append(f"{label}需要填数字")
        return None
    if not low <= value <= high:
        errors.append(f"{label}请填 {low:g}–{high:g} 之间")
        return None
    return value


@app.route("/plan", methods=["GET"])
def plan() -> str:
    """按 BMR / TDEE 推算目标热量，并给出食堂菜品搭配方案。"""
    args = request.args
    form = {
        "gender": args.get("gender", "male"),
        "age": args.get("age", ""),
        "height": args.get("height", ""),
        "weight": args.get("weight", ""),
        "activity": args.get("activity", "light"),
        "goal": args.get("goal", "fat_loss"),
        "meal": args.get("meal", "lunch"),
        "bmr": args.get("bmr", ""),
    }

    submitted = bool(args.get("weight") or args.get("height") or args.get("age"))
    errors: list[str] = []
    target = None
    plans: list = []
    meal = MEAL_BY_KEY.get(form["meal"], MEAL_BY_KEY["lunch"])
    meal_kcal = meal_protein = 0.0

    if submitted:
        if form["gender"] not in {"male", "female"}:
            errors.append("请选择性别")
        if form["activity"] not in ACTIVITY_BY_KEY:
            errors.append("请选择活动量")
        if form["goal"] not in GOAL_BY_KEY:
            errors.append("请选择目标")

        age = _parse_number(form["age"], "年龄", 10, 100, errors)
        height = _parse_number(form["height"], "身高", 120, 230, errors)
        weight = _parse_number(form["weight"], "体重", 30, 200, errors)
        manual_bmr = _parse_number(
            form["bmr"], "基础代谢", 600, 4000, errors, required=False
        )

        if not errors and age and height and weight:
            target = build_target(
                gender=form["gender"],
                weight_kg=weight,
                height_cm=height,
                age=int(age),
                activity_key=form["activity"],
                goal_key=form["goal"],
                manual_bmr=manual_bmr,
            )
            meal_kcal = target.target_kcal * meal.ratio
            meal_protein = target.protein_g * meal.ratio
            plans = build_plans(meal_kcal, meal_protein, form["goal"])

    return render_template(
        "plan.html",
        app_name="DietBalance",
        year=datetime.now().year,
        form=form,
        errors=errors,
        submitted=submitted,
        target=target,
        plans=plans,
        meal=meal,
        meal_kcal=meal_kcal,
        meal_protein=meal_protein,
        activity_levels=ACTIVITY_LEVELS,
        goals=GOALS,
        meals=MEALS,
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """供容器编排 / 负载均衡做存活探测。"""
    return {"status": "ok"}


if __name__ == "__main__":
    # 仅用于本地开发；生产请使用 gunicorn / waitress 启动 wsgi:app
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=port, debug=debug)
