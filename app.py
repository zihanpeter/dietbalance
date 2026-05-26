import os
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from food_api import search_food
from sources.dishes import load_dishes

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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """供容器编排 / 负载均衡做存活探测。"""
    return {"status": "ok"}


if __name__ == "__main__":
    # 仅用于本地开发；生产请使用 gunicorn / waitress 启动 wsgi:app
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=port, debug=debug)
