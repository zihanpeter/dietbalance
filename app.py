import os
import secrets
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from food_api import search_food
from sources import accounts, visits
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


def _read_env_value(key: str) -> str:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return ""
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


# Flask 需要稳定的 SECRET_KEY，优先环境变量 / .env，否则持久化到本地文件
_secret = os.environ.get("SECRET_KEY") or _read_env_value("SECRET_KEY")
if not _secret:
    _secret_file = Path(__file__).resolve().parent / ".cache" / "secret_key"
    try:
        _secret_file.parent.mkdir(parents=True, exist_ok=True)
        if _secret_file.exists():
            _secret = _secret_file.read_text(encoding="utf-8").strip()
        if not _secret:
            _secret = secrets.token_hex(32)
            _secret_file.write_text(_secret, encoding="utf-8")
    except OSError:
        _secret = secrets.token_hex(32)
app.config["SECRET_KEY"] = _secret

try:
    accounts.init_db()
except accounts.AccountError:
    # .cache 不可写时仍允许站点启动；注册/登录时再报错
    pass


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


@app.before_request
def _count_page_view() -> None:
    """统计页面浏览量；健康检查与静态资源不计入。"""
    if request.method != "GET":
        return
    endpoint = request.endpoint
    if endpoint in (None, "static", "healthz"):
        return
    visits.increment(request.path)


@app.context_processor
def _inject_globals():
    current_user = None
    user_id = session.get("user_id")
    if user_id:
        current_user = accounts.get_user(int(user_id))
        if current_user is None:
            session.pop("user_id", None)
    return {
        "visit_count": visits.total(),
        "current_user": current_user,
        "app_name": "DietBalance",
        "year": datetime.now().year,
    }


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


def _default_plan_form() -> dict[str, str]:
    return {
        "gender": "male",
        "age": "",
        "height": "",
        "weight": "",
        "activity": "light",
        "goal": "fat_loss",
        "meal": "lunch",
        "bmr": "",
    }


@app.route("/", methods=["GET"])
def index() -> str:
    """封面 / 落地页。"""
    return render_template(
        "landing.html",
        dish_count=len(load_dishes()),
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


def _form_from_request() -> dict[str, str]:
    return {
        "gender": request.values.get("gender", "male"),
        "age": request.values.get("age", ""),
        "height": request.values.get("height", ""),
        "weight": request.values.get("weight", ""),
        "activity": request.values.get("activity", "light"),
        "goal": request.values.get("goal", "fat_loss"),
        "meal": request.values.get("meal", "lunch"),
        "bmr": request.values.get("bmr", ""),
    }


@app.route("/plan", methods=["GET", "POST"])
def plan() -> str:
    """按 BMR / TDEE 推算目标热量，并给出食堂菜品搭配方案。"""
    current_user = None
    user_id = session.get("user_id")
    if user_id:
        current_user = accounts.get_user(int(user_id))

    # 保存身体档案到账号
    if request.method == "POST" and request.form.get("action") == "save_profile":
        if not current_user:
            flash("请先登录后再保存身体数据。", "error")
            return redirect(url_for("login", next=url_for("plan")))
        form = _form_from_request()
        save_errors: list[str] = []
        if form["gender"] not in {"male", "female"}:
            save_errors.append("请选择性别")
        if form["activity"] not in ACTIVITY_BY_KEY:
            save_errors.append("请选择活动量")
        if form["goal"] not in GOAL_BY_KEY:
            save_errors.append("请选择目标")
        if form["meal"] not in MEAL_BY_KEY:
            save_errors.append("请选择餐次")
        _parse_number(form["age"], "年龄", 10, 100, save_errors)
        _parse_number(form["height"], "身高", 120, 230, save_errors)
        _parse_number(form["weight"], "体重", 30, 200, save_errors)
        _parse_number(form["bmr"], "基础代谢", 600, 4000, save_errors, required=False)
        if save_errors:
            for msg in save_errors:
                flash(msg, "error")
            return redirect(url_for("plan", **{k: v for k, v in form.items() if v}))
        try:
            accounts.save_profile(current_user.id, form)
            flash("身体数据与活动量已保存到账号。", "ok")
        except accounts.AccountError as exc:
            flash(str(exc), "error")
        return redirect(url_for("plan", **{k: v for k, v in form.items() if v}))

    args = request.args
    has_query = any(args.get(k) for k in ("weight", "height", "age", "gender", "activity"))
    form = _default_plan_form()
    if current_user and not has_query:
        form.update(current_user.profile_for_form())
    # URL 参数优先（便于分享 / 刚保存后回跳）
    for key in form:
        if args.get(key) is not None and args.get(key) != "":
            form[key] = args.get(key, form[key])

    submitted = bool(args.get("weight") or args.get("height") or args.get("age"))
    errors: list[str] = []
    target = None
    plans: list = []
    meal = MEAL_BY_KEY.get(form["meal"], MEAL_BY_KEY["lunch"])
    meal_kcal = meal_protein = meal_carb = 0.0

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
            meal_carb = target.carb_g * meal.ratio
            plans = build_plans(
                meal_kcal,
                meal_protein,
                form["goal"],
                meal_carb_g=meal_carb,
            )

    return render_template(
        "plan.html",
        form=form,
        errors=errors,
        submitted=submitted,
        target=target,
        plans=plans,
        meal=meal,
        meal_kcal=meal_kcal,
        meal_protein=meal_protein,
        meal_carb=meal_carb,
        activity_levels=ACTIVITY_LEVELS,
        goals=GOALS,
        meals=MEALS,
        profile_saved=bool(current_user and current_user.profile),
    )


@app.route("/register", methods=["GET", "POST"])
def register() -> str:
    if session.get("user_id"):
        return redirect(url_for("plan"))

    error = ""
    username = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        try:
            if password != password2:
                raise accounts.AccountError("两次输入的密码不一致")
            user = accounts.register(username, password)
            session.clear()
            session["user_id"] = user.id
            flash("注册成功，已自动登录。可以填写并保存身体数据了。", "ok")
            return redirect(url_for("plan"))
        except accounts.AccountError as exc:
            error = str(exc)

    return render_template("auth.html", mode="register", error=error, username=username)


@app.route("/login", methods=["GET", "POST"])
def login() -> str:
    if session.get("user_id"):
        return redirect(url_for("plan"))

    error = ""
    username = ""
    next_url = request.values.get("next") or url_for("plan")
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        try:
            user = accounts.authenticate(username, password)
            session.clear()
            session["user_id"] = user.id
            flash(f"欢迎回来，{user.username}。", "ok")
            if next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("plan"))
        except accounts.AccountError as exc:
            error = str(exc)

    return render_template(
        "auth.html",
        mode="login",
        error=error,
        username=username,
        next_url=next_url,
    )


@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    flash("已退出登录。", "ok")
    return redirect(url_for("index"))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """供容器编排 / 负载均衡做存活探测。"""
    return {"status": "ok"}


if __name__ == "__main__":
    # 仅用于本地开发；生产请使用 gunicorn / waitress 启动 wsgi:app
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=port, debug=debug)
