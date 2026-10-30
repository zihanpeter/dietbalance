"""WSGI 入口。生产环境通过 Gunicorn / Waitress 启动：

    gunicorn -c gunicorn.conf.py wsgi:app
    waitress-serve --listen=0.0.0.0:8000 wsgi:app
"""
from app import app

__all__ = ["app"]
