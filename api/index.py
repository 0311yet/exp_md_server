"""Vercel serverless 入口：暴露 app/main.py 里的 FastAPI app。"""
from app.main import app as app

__all__ = ["app"]
