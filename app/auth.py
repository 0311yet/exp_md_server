"""认证。

经验库无须加解锁（内容是公开知识），所以比 key_server 简单：
- Web：密码登录 → 校验密码哈希 → 发 session cookie
- Agent：Bearer token → sha256 比对 → 过期校验 + 自动续期

所有 datetime 一律 naive UTC，避免 offset-naive vs aware 比较错误。
"""
from __future__ import annotations
import datetime as dt
import hashlib
import hmac
import secrets

from fastapi import Request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from . import config, db

SESSION_COOKIE = "explib_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # Web session 7 天

TOKEN_TTL_DAYS = 30
TOKEN_RENEW_THRESHOLD_DAYS = 7


def utcnow_naive() -> dt.datetime:
    return dt.datetime.utcnow()


_serializer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="web-session")


# ---------- 密码哈希：PBKDF2-HMAC-SHA256 ----------

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return "pbkdf2$200000$" + salt.hex() + "$" + h.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        salt = bytes.fromhex(salt_hex)
        iters_n = int(iters)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters_n)
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


def ensure_password_hash() -> None:
    """确保密码哈希与当前 LOGIN_PASSWORD 一致（首次创建或密码变更后自动重建）。"""
    stored = db.get_password_hash()
    if stored is None:
        db.set_password_hash(_hash_password(config.LOGIN_PASSWORD))
        return
    if not _verify_password(config.LOGIN_PASSWORD, stored):
        db.set_password_hash(_hash_password(config.LOGIN_PASSWORD))


def verify_password(password: str) -> bool:
    """校验登录密码。经验库无须解锁，只校验密码即可。"""
    stored = db.get_password_hash()
    if not stored:
        return False
    return _verify_password(password, stored)


# ---------- Web session ----------

def make_session_cookie() -> str:
    return _serializer.dumps({"u": 1})


def parse_session_cookie(raw: str) -> bool:
    """返回是否有效登录态。"""
    try:
        data = _serializer.loads(raw, max_age=SESSION_MAX_AGE)
        return bool(data.get("u"))
    except (BadSignature, SignatureExpired):
        return False


# ---------- Agent token ----------

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_new_token_value() -> str:
    return secrets.token_urlsafe(32)


def renew_if_needed(row) -> None:
    now = utcnow_naive()
    exp = row.expires_at.replace(tzinfo=None) if row.expires_at.tzinfo else row.expires_at
    remaining_days = (exp - now).total_seconds() / 86400.0
    if remaining_days < TOKEN_RENEW_THRESHOLD_DAYS:
        new_expires = now + dt.timedelta(days=TOKEN_TTL_DAYS)
        db.update_token(row, expires_at=new_expires)


def authenticate_api_request(request: Request):
    """从 Authorization: Bearer xxx 取 token，返回对应 AIToken 或 None。"""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    raw = auth_header[7:].strip()
    if not raw:
        return None
    h = token_hash(raw)
    row = db.get_token_by_hash(h)
    if not row or row.status != "approved":
        return None
    now = utcnow_naive()
    exp = row.expires_at.replace(tzinfo=None) if row.expires_at.tzinfo else row.expires_at
    if exp < now:
        return None
    ip = request.client.host if request.client else None
    db.update_token(row, last_used_at=now, last_ip=ip)
    renew_if_needed(row)
    return row
