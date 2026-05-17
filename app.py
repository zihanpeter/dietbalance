import os
from datetime import datetime

from flask import Flask, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from food_api import search_food

app = Flask(__name__)
app.config["PREFERRED_URL_SCHEME"] = os.environ.get("PREFERRED_URL_SCHEME", "https")

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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """供容器编排 / 负载均衡做存活探测。"""
    return {"status": "ok"}


if __name__ == "__main__":
    # 仅用于本地开发；生产请使用 gunicorn / waitress 启动 wsgi:app
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=port, debug=debug)
