"""FastAPI 主应用：Web + AI API。经验库（Experience Library）。"""
from __future__ import annotations
import datetime as dt
import hmac
import secrets

import os
from fastapi import FastAPI, Request, Response, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse

from . import config, auth, db, mdparse

app = FastAPI(title="Experience Library")

# Vercel 自动从 public/ 目录服务静态文件（CDN，无 Python 开销）
# 本地 uvicorn 不走 public/，所以手动挂载 public/ 为 /static（向后兼容 /style.css → public/style.css）
app.mount("/static", StaticFiles(directory="public"), "static")

# 本地开发（SQLite，无 TLS）时 session cookie 不加 Secure flag
# Vercel 始终走 HTTPS，可以加 Secure
_VERCEL_URL = os.getenv("VERCEL_URL", "")
_SESSIONS_SECURE = bool(_VERCEL_URL)

# ---------- CSRF 保护 ----------
def _make_csrf_token() -> str:
    return secrets.token_hex(32)


def _check_csrf(request: Request) -> None:
    cookie_token = request.cookies.get("csrf_token", "")
    header_token = request.headers.get("x-csrf-token", "")
    if not cookie_token or not header_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


def _set_cookie(response: Response, name: str, value: str, max_age: int = 3600, secure: bool = False) -> None:
    from urllib.parse import quote
    flags = f"Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
    if secure:
        flags += "; Secure"
    response.headers.append("Set-Cookie", f"{name}={quote(value, safe='')}; {flags}")


# ========== 内联模板 ==========
import jinja2
from .templates import LOGIN_HTML
_jinja_env = jinja2.Environment(
    loader=jinja2.DictLoader({
        "login.html": LOGIN_HTML,
    }),
    autoescape=True,
)


def render(name: str, **context) -> HTMLResponse:
    """渲染模板并返回 HTMLResponse。dashboard 由 make_dashboard_html 单独处理。"""
    if name == "dashboard.html" and "_experiences" in context:
        from . import templates as _tpl
        html = _tpl.make_dashboard_html(
            csrf_token=context.get("csrf_token", ""),
            experiences=context.get("_experiences"),
            pending=context.get("_pending"),
            tokens=context.get("_tokens"),
        )
        return HTMLResponse(html)
    template = _jinja_env.get_template(name)
    html = template.render(**{k: v for k, v in context.items() if v is not None})
    return HTMLResponse(html)


# ========== 启动时初始化 ==========
_init_done = False

@app.middleware("http")
async def init_once_middleware(request: Request, call_next):
    global _init_done
    if not _init_done:
        db.init_db()
        auth.ensure_password_hash()
        _init_done = True
    return await call_next(request)


# ========== Web 页面路由 ==========
@app.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    token = _make_csrf_token()
    resp = render("login.html", csrf_token=token)
    _set_cookie(resp, "csrf_token", token, max_age=3600)
    return resp


@app.post("/login")
def do_login(password: str = Form(...), request: Request = None):
    ip = request.client.host if request and request.client else "unknown"
    if not auth.verify_password(password):
        return JSONResponse({"ok": False, "error": "密码错误"}, status_code=401)
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, auth.SESSION_COOKIE, auth.make_session_cookie(),
                max_age=auth.SESSION_MAX_AGE, secure=_SESSIONS_SECURE)
    return resp


@app.post("/logout")
def logout(request: Request = None):
    _check_csrf(request)
    resp = JSONResponse({"ok": True})
    resp.headers.append("Set-Cookie", f"{auth.SESSION_COOKIE}=; Path=/; Max-Age=0")
    resp.headers.append("Set-Cookie", f"csrf_token=; Path=/; Max-Age=0")
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if not auth.parse_session_cookie(request.cookies.get(auth.SESSION_COOKIE, "")):
        return RedirectResponse(url="/login", status_code=302)
    token = _make_csrf_token()

    experiences = db.list_experiences(limit=1000)
    pending = db.list_pending()
    tokens = db.list_tokens()

    resp = render(
        "dashboard.html",
        csrf_token=token,
        _experiences=experiences,
        pending=pending,
        tokens=tokens,
    )
    _set_cookie(resp, "csrf_token", token, max_age=3600)
    return resp


@app.post("/dashboard/delete_token")
def delete_token_endpoint(token_id: int = Form(...), request: Request = None):
    if not auth.parse_session_cookie(request.cookies.get(auth.SESSION_COOKIE, "")):
        return {"ok": False, "error": "未登录"}
    _check_csrf(request)
    ok = db.delete_token(token_id)
    return {"ok": ok}


@app.post("/dashboard/delete_experience")
def delete_experience_endpoint(exp_id: int = Form(...), request: Request = None):
    if not auth.parse_session_cookie(request.cookies.get(auth.SESSION_COOKIE, "")):
        return {"ok": False, "error": "未登录"}
    _check_csrf(request)
    ok = db.delete_experience(exp_id)
    return {"ok": ok}


# ========== AI 连接流程（敲门）==========
@app.post("/api/connect")
def connect(client_name: str = Form(...), request: Request = None):
    if not client_name or not client_name.strip():
        return JSONResponse({"ok": False, "error": "client_name 不能为空"}, status_code=400)
    client_name = client_name.strip()[:64]
    ip = request.client.host if request and request.client else "unknown"
    connect_id = secrets.token_hex(32)
    ua = request.headers.get("user-agent", "")
    db.create_pending(connect_id, client_name, ip, ua)
    return {"ok": True, "connect_id": connect_id}


@app.get("/api/connect/{connect_id}/status")
def connect_status(connect_id: str):
    pending = db.get_pending(connect_id)
    if not pending:
        return {"status": "invalid"}
    if pending.status == "approved":
        token = auth.create_new_token_value()
        token_hash = auth.token_hash(token)
        new_expires = auth.utcnow_naive() + dt.timedelta(days=auth.TOKEN_TTL_DAYS)
        db.create_token(pending.client_name, token_hash, new_expires, pending.ip)
        db.set_pending_status(pending.id, "issued")
        return {"status": "approved", "token": token}
    if pending.status == "issued":
        return {"status": "approved"}
    if pending.status == "denied":
        return {"status": "denied"}
    return {"status": "pending"}


@app.post("/connect/{connect_id}/approve")
def approve(connect_id: str, request: Request = None):
    if not auth.parse_session_cookie(request.cookies.get(auth.SESSION_COOKIE, "")):
        return {"ok": False, "error": "未登录"}
    _check_csrf(request)
    pending = db.get_pending(connect_id)
    if not pending:
        return {"ok": False, "error": "连接不存在"}
    db.set_pending_status(pending.id, "approved")
    return {"ok": True}


@app.post("/connect/{connect_id}/deny")
def deny(connect_id: str, request: Request = None):
    if not auth.parse_session_cookie(request.cookies.get(auth.SESSION_COOKIE, "")):
        return {"ok": False, "error": "未登录"}
    _check_csrf(request)
    pending = db.get_pending(connect_id)
    if not pending:
        return {"ok": False, "error": "连接不存在"}
    db.set_pending_status(pending.id, "denied")
    return {"ok": True}


# ========== AI API（需 Bearer token）==========
def require_auth(request: Request):
    """经验库 API 的入口鉴权函数（复用 key_server）。"""
    token_row = auth.authenticate_api_request(request)
    if not token_row:
        raise HTTPException(status_code=401, detail="未授权")
    return token_row


@app.get("/api/experiences")
def list_experiences_api(
    request: Request,
    limit: int = 100, offset: int = 0,
    tag: str | None = None, project: str | None = None,
    keyword: str | None = None
):
    """列出经验（Web + Agent 共用）。"""
    require_auth(request)
    rows = db.list_experiences(limit, offset, tag, project, keyword)
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "title": r.title,
            "tags": r.tags,
            "project": r.project,
            "summary": r.summary or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        })
    return {"ok": True, "items": out}


@app.get("/api/experiences/{exp_id}")
def get_experience_api(exp_id: int, request: Request):
    """获取单条经验完整内容（含 raw_md）。"""
    require_auth(request)
    exp = db.get_experience_by_id(exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="经验不存在")
    return {
        "ok": True,
        "title": exp.title,
        "tags": exp.tags,
        "project": exp.project,
        "summary": exp.summary or "",
        "body_md": exp.body_md,
        "raw_md": exp.raw_md,
        "created_at": exp.created_at.isoformat() if exp.created_at else "",
        "updated_at": exp.updated_at.isoformat() if exp.updated_at else "",
    }


@app.post("/api/experiences")
def upload_experience_api(request: Request, raw_md: str = Form(...)):
    """Agent 上传新经验（必需有 title）。"""
    require_auth(request)
    fields = mdparse.extract_experience_fields(raw_md)
    if not fields:
        raise HTTPException(status_code=400, detail="MD 中缺少 title 字段或格式错误")
    title, tags, project, summary, body_md = fields

    # 简单的去重：同 title 的，按其 id 更新；不存在则新增
    existing = db.list_experiences(limit=1, keyword=title)
    if existing:
        exp = db.upsert_experience(title, tags, project, body_md, raw_md, summary,
                                   exp_id=existing[0].id)
    else:
        exp = db.upsert_experience(title, tags, project, body_md, raw_md, summary)

    return {
        "ok": True,
        "id": exp.id,
        "title": exp.title,
        "tags": exp.tags,
        "project": exp.project,
        "summary": exp.summary or "",
        "created_at": exp.created_at.isoformat() if exp.created_at else "",
        "updated_at": exp.updated_at.isoformat() if exp.updated_at else "",
    }


@app.put("/api/experiences/{exp_id}")
def update_experience_api(exp_id: int, request: Request, raw_md: str = Form(...)):
    """Agent 修改已有经验（必须包含 title）。"""
    require_auth(request)
    exp = db.get_experience_by_id(exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="经验不存在")

    fields = mdparse.extract_experience_fields(raw_md)
    if not fields:
        raise HTTPException(status_code=400, detail="MD 中缺少 title 字段或格式错误")
    title, tags, project, summary, body_md = fields

    exp = db.upsert_experience(title, tags, project, body_md, raw_md, summary,
                            exp_id=exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="经验不存在")

    return {
        "ok": True,
        "id": exp.id,
        "title": exp.title,
        "tags": exp.tags,
        "project": exp.project,
        "summary": exp.summary or "",
        "created_at": exp.created_at.isoformat() if exp.created_at else "",
        "updated_at": exp.updated_at.isoformat() if exp.updated_at else "",
    }


# ========== /api/dashboard（session 认证，供前端轮询用）==========
@app.get("/api/dashboard/data")
def dashboard_data_api(request: Request):
    if not auth.parse_session_cookie(request.cookies.get(auth.SESSION_COOKIE, "")):
        return JSONResponse({"ok": False, "error": "未登录"}, status_code=401)
    experiences = db.list_experiences(limit=1000)
    pending = db.list_pending()
    tokens = db.list_tokens()
    return {
        "ok": True,
        "experiences": [
            {
                "id": e.id,
                "title": e.title,
                "tags": e.tags,
                "project": e.project,
                "summary": e.summary or "",
                "created_at": e.created_at.isoformat() if e.created_at else "",
                "updated_at": e.updated_at.isoformat() if e.updated_at else "",
            }
            for e in experiences
        ],
        "pending": [
            {
                "id": p.id,
                "connect_id": p.connect_id,
                "client_name": p.client_name,
                "ip": p.ip or "",
                "created_at": p.created_at.isoformat() if p.created_at else "",
            }
            for p in pending
        ],
        "tokens": [
            {
                "id": t.id,
                "client_name": t.client_name,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else "",
                "expires_at": t.expires_at.isoformat() if t.expires_at else "",
                "last_used_at": (t.last_used_at.isoformat() if t.last_used_at else ""),
            }
            for t in tokens
        ],
    }


# ========== /health ==========
@app.get("/health")
def health():
    return {"ok": True, "locked": False}  # 经验库不锁定，始终 ok
