"""配置加载：从环境变量 / .env 读取。

经验库不需要加密（内容是公开知识），所以没有 KDF_SALT / KV / MASTER_KEY 那一套。
只保留：登录密码、session 密钥、Turso（可选）。
"""
from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise RuntimeError(f"环境变量 {name} 未设置，请检查 .env")
    return val


LOGIN_PASSWORD: str = _env("LOGIN_PASSWORD")
SESSION_SECRET: str = _env("SESSION_SECRET")

# 本地 / VPS 用 SQLite；Vercel + Turso 用 TURSO_DATABASE_URL
DB_FILE: str = os.getenv("DB_FILE", str(BASE_DIR / "data" / "exp_md.db"))
TURSO_DATABASE_URL: str = os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")

# 确保 SQLite 文件所在目录存在（SQLite 不会自动建目录）
if not TURSO_DATABASE_URL:
    _db_dir = Path(DB_FILE).parent
    _db_dir.mkdir(parents=True, exist_ok=True)
