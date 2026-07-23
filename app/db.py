"""数据库层：SQLite（VPS 本地）或 httpx + Turso HTTP API（Vercel）。

切换方式：环境变量 TURSO_DATABASE_URL 非空时走 Turso 模式。
"""
from __future__ import annotations
import datetime as dt
import httpx

from . import config

_USING_TURSO = bool(config.TURSO_DATABASE_URL)


# ============================================================
# 初始化
# ============================================================
if _USING_TURSO:
    _TURSO_BASE = config.TURSO_DATABASE_URL.rstrip("/").replace("libsql://", "https://", 1)
    _TURSO_HEADERS = {"Authorization": f"Bearer {config.TURSO_AUTH_TOKEN}"}

    def _http() -> httpx.Client:
        return httpx.Client(base_url=_TURSO_BASE, headers=_TURSO_HEADERS,
                            follow_redirects=True, timeout=30.0)

    def _serialize(val):
        """Python 值 → Turso typed value dict。"""
        if val is None:
            return {"type": "null", "value": "nil"}
        if isinstance(val, bool):
            return {"type": "integer", "value": "1" if val else "0"}
        if isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        if isinstance(val, float):
            return {"type": "float", "value": str(val)}
        if isinstance(val, bytes):
            import base64
            return {"type": "blob", "value": base64.b64encode(val).decode()}
        if isinstance(val, dt.datetime):
            return {"type": "text", "value": val.isoformat()}
        return {"type": "text", "value": str(val)}

    def _run(sql: str, args: tuple = ()) -> list[dict]:
        """Turso: 执行 SQL 返回行列表。"""
        with _http() as client:
            r = client.post("/v2/pipeline", json={
                "requests": [{"type": "execute", "stmt": {"sql": sql, "args": [_serialize(a) for a in args]}}]
            })
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                return []
            res = results[0]
            if res.get("type") == "error":
                raise RuntimeError(f"SQL error: {res}")
            resp = res.get("response", {})
            result_data = resp.get("result", {})
            cols = result_data.get("cols", [])
            rows = result_data.get("rows", [])
            out = []
            for row in rows:
                obj = {}
                for i, cell in enumerate(row):
                    col_name = cols[i]["name"] if i < len(cols) else f"col{i}"
                    obj[col_name] = _deserialize(cell, col_name)
                out.append(obj)
            return out

    def _exec(sql: str, args: tuple = ()) -> None:
        """Turso: 执行写 SQL。"""
        with _http() as client:
            r = client.post("/v2/pipeline", json={
                "requests": [{"type": "execute", "stmt": {"sql": sql, "args": [_serialize(a) for a in args]}}]
            })
            r.raise_for_status()

    def _deserialize(v, col_name: str = ""):
        """Turso {type,value} → Python 对象。col_name 决定是否将 text 解析为 datetime。"""
        if not isinstance(v, dict) or "type" not in v:
            return v
        t = v["type"]
        val = v.get("value")
        if t == "integer":
            return int(val) if val is not None else 0
        if t == "float":
            return float(val) if val is not None else 0.0
        if t == "null":
            return None
        if t == "text":
            if col_name and any(k in col_name for k in ("_at", "time", "date")):
                val_clean = val.replace("Z", "+00:00") if val else ""
                try:
                    return dt.datetime.fromisoformat(val_clean)
                except ValueError:
                    pass
            return val if val is not None else ""
        if t == "blob":
            import base64
            return base64.b64decode(val) if val else b""
        return v

    def _row(d: dict):
        """字典 → 属性对象，兼容调用方的 .id .title 等访问。"""
        class Row:
            def __init__(self, data):
                for k, v in data.items():
                    setattr(self, k, _deserialize(v, col_name=k))
        return Row(d) if d else None

    def init_db():
        stmts = [
            "CREATE TABLE IF NOT EXISTS experiences (id INTEGER PRIMARY KEY, title TEXT, tags TEXT, project TEXT, body_md TEXT, raw_md TEXT, summary TEXT, created_at TEXT, updated_at TEXT)",
            "CREATE TABLE IF NOT EXISTS ai_tokens (id INTEGER PRIMARY KEY, client_name TEXT, token_hash TEXT UNIQUE NOT NULL, status TEXT DEFAULT 'approved', created_at TEXT, expires_at TEXT, last_used_at TEXT, last_ip TEXT)",
            "CREATE TABLE IF NOT EXISTS pending_connections (id INTEGER PRIMARY KEY, connect_id TEXT UNIQUE NOT NULL, client_name TEXT, ip TEXT, ua TEXT, status TEXT DEFAULT 'pending', created_at TEXT)",
            "CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, value TEXT)",
            "CREATE INDEX IF NOT EXISTS idx_experiences_title ON experiences(title)",
            "CREATE INDEX IF NOT EXISTS idx_experiences_tags ON experiences(tags)",
            "CREATE INDEX IF NOT EXISTS idx_experiences_project ON experiences(project)",
            "CREATE INDEX IF NOT EXISTS idx_ai_tokens_hash ON ai_tokens(token_hash)",
        ]
        for s in stmts:
            _exec(s)

else:
    from sqlmodel import Session, create_engine, select, SQLModel
    from .models import AIToken, Experience, PendingConnection, Setting

    _engine = create_engine(
        f"sqlite:///{config.DB_FILE}",
        echo=False, connect_args={"check_same_thread": False},
    )

    def get_session():
        with Session(_engine) as s:
            yield s

    def init_db():
        SQLModel.metadata.create_all(_engine)


# ============================================================
# 公开函数（模式无关，内部引用 _USING_TURSO）
# ============================================================

SETTING_PWD_HASH = "login_password_hash"


def get_password_hash() -> str | None:
    if _USING_TURSO:
        rows = _run("SELECT key, value FROM settings WHERE key = ?", (SETTING_PWD_HASH,))
        if rows:
            return rows[0].get("value")
        return None
    with Session(_engine) as s:
        row = s.get(Setting, SETTING_PWD_HASH)
        return row.value if row else None


def set_password_hash(h: str) -> None:
    if _USING_TURSO:
        _exec("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (SETTING_PWD_HASH, h))
        return
    with Session(_engine) as s:
        row = s.get(Setting, SETTING_PWD_HASH)
        if row:
            row.value = h
        else:
            s.add(Setting(key=SETTING_PWD_HASH, value=h))
        s.commit()


# ============================================================
# Experience CRUD
# ============================================================

def list_experiences(limit: int = 100, offset: int = 0,
                     tag_filter: str | None = None,
                     project_filter: str | None = None,
                     keyword: str | None = None) -> list:
    """返回 Experience 列表（可筛选）。"""
    if _USING_TURSO:
        where = []
        args = []
        if tag_filter:
            where.append("tags LIKE ?")
            args.append(f"%{tag_filter}%")
        if project_filter:
            where.append("project LIKE ?")
            args.append(f"%{project_filter}%")
        if keyword:
            where.append("(title LIKE ? OR body_md LIKE ?)")
            args.extend([f"%{keyword}%", f"%{keyword}%"])
        where_sql = " AND ".join(where) if where else "1=1"
        rows = _run(f"""
            SELECT id, title, tags, project, summary, created_at, updated_at
            FROM experiences
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, args + [limit, offset])
        return [_row_experiences(r) for r in rows]
    with Session(_engine) as s:
        q = select(Experience)
        if tag_filter:
            q = q.where(Experience.tags.like(f"%{tag_filter}%"))
        if project_filter:
            q = q.where(Experience.project.like(f"%{project_filter}%"))
        if keyword:
            q = q.where(
                (Experience.title.like(f"%{keyword}%")) |
                (Experience.body_md.like(f"%{keyword}%"))
            )
        q = q.order_by(Experience.created_at.desc())
        if offset:
            q = q.offset(offset)
        if limit:
            q = q.limit(limit)
        return list(s.exec(q).all())


def get_experience_by_id(exp_id: int) -> Experience | None:
    """按 ID 获取一条经验（完整）。"""
    if _USING_TURSO:
        rows = _run("SELECT id, title, tags, project, body_md, raw_md, summary, created_at, updated_at FROM experiences WHERE id = ?", (exp_id,))
        return _row_experiences(rows[0]) if rows else None
    with Session(_engine) as s:
        return s.exec(select(Experience).where(Experience.id == exp_id)).first()


def upsert_experience(title: str, tags: str, project: str,
                      body_md: str, raw_md: str, summary: str = "",
                      exp_id: int | None = None):
    """新增或更新一条经验。

    - exp_id 为 None：新增一条，返回新建对象
    - exp_id 非 None：按 ID 更新（不存在返回 None）
    """
    if _USING_TURSO:
        now = dt.datetime.utcnow().isoformat()
        if exp_id is None:
            _exec(
                "INSERT INTO experiences (title, tags, project, body_md, raw_md, summary, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (title, tags, project, body_md, raw_md, summary, now, now),
            )
            rows = _run("SELECT id, title, tags, project, body_md, raw_md, summary, created_at, updated_at FROM experiences WHERE id = (SELECT MAX(id) FROM experiences)")
            return _row_experiences(rows[0]) if rows else None
        _exec(
            "UPDATE experiences SET title=?, tags=?, project=?, body_md=?, raw_md=?, summary=?, updated_at=? WHERE id = ?",
            (title, tags, project, body_md, raw_md, summary, now, exp_id),
        )
        rows = _run("SELECT id, title, tags, project, body_md, raw_md, summary, created_at, updated_at FROM experiences WHERE id = ?", (exp_id,))
        return _row_experiences(rows[0]) if rows else None
    with Session(_engine) as s:
        if exp_id is not None:
            row = s.exec(select(Experience).where(Experience.id == exp_id)).first()
            if not row:
                return None
            row.title = title
            row.tags = tags
            row.project = project
            row.body_md = body_md
            row.raw_md = raw_md
            row.summary = summary
            row.updated_at = dt.datetime.utcnow()
        else:
            row = Experience(
                title=title, tags=tags, project=project,
                body_md=body_md, raw_md=raw_md, summary=summary
            )
            s.add(row)
        s.commit()
        s.refresh(row)
        return row


def delete_experience(exp_id: int) -> bool:
    """删除一条经验（不可逆）。"""
    if _USING_TURSO:
        if not _run("SELECT id FROM experiences WHERE id = ?", (exp_id,)):
            return False
        _exec("DELETE FROM experiences WHERE id = ?", (exp_id,))
        return True
    with Session(_engine) as s:
        row = s.exec(select(Experience).where(Experience.id == exp_id)).first()
        if row:
            s.delete(row)
            s.commit()
            return True
        return False


def _row_experiences(d: dict):
    """字典 → 属性对象（去掉 raw_md 以免泄露）。"""
    class Row:
        def __init__(self, data):
            for k, v in data.items():
                setattr(self, k, v)
    return Row(d)


# ============================================================
# Token 相关（复用 key_server）
# ============================================================

def get_token_by_hash(token_hash: str):
    if _USING_TURSO:
        rows = _run(
            "SELECT id, client_name, token_hash, expires_at, last_used_at, last_ip, status, created_at"
            " FROM ai_tokens WHERE token_hash = ?", (token_hash,))
        return _row(rows[0]) if rows else None
    with Session(_engine) as s:
        return s.exec(select(AIToken).where(AIToken.token_hash == token_hash)).first()


def list_tokens() -> list:
    if _USING_TURSO:
        return [_row(r) for r in _run(
            "SELECT id, client_name, token_hash, expires_at, last_used_at, last_ip, status, created_at"
            " FROM ai_tokens ORDER BY created_at DESC")]
    with Session(_engine) as s:
        return list(s.exec(select(AIToken).order_by(AIToken.created_at.desc())).all())


def create_token(client_name: str, token_hash: str, expires_at: dt.datetime,
                 ip: str | None):
    if _USING_TURSO:
        now = dt.datetime.utcnow().isoformat()
        _exec(
            "INSERT INTO ai_tokens (client_name, token_hash, expires_at, last_ip, status, created_at)"
            " VALUES (?, ?, ?, ?, 'approved', ?)",
            (client_name, token_hash, expires_at.isoformat(), ip, now),
        )
        rows = _run(
            "SELECT id, client_name, token_hash, expires_at, last_used_at, last_ip, status, created_at"
            " FROM ai_tokens WHERE token_hash = ?", (token_hash,))
        return _row(rows[0])
    with Session(_engine) as s:
        row = AIToken(client_name=client_name, token_hash=token_hash,
                      expires_at=expires_at, last_ip=ip)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def update_token(row, expires_at: dt.datetime | None = None,
                 last_used_at: dt.datetime | None = None,
                 last_ip: str | None = None, status: str | None = None) -> None:
    if _USING_TURSO:
        parts, args = [], []
        if expires_at:
            parts.append("expires_at = ?"); args.append(expires_at.isoformat())
        if last_used_at:
            parts.append("last_used_at = ?"); args.append(last_used_at.isoformat())
        if last_ip:
            parts.append("last_ip = ?"); args.append(last_ip)
        if status:
            parts.append("status = ?"); args.append(status)
        if parts:
            args.append(row.id)
            _exec(f"UPDATE ai_tokens SET {', '.join(parts)} WHERE id = ?", tuple(args))
        return
    with Session(_engine) as s:
        db_row = s.get(AIToken, row.id)
        if expires_at is not None:
            db_row.expires_at = expires_at
        if last_used_at is not None:
            db_row.last_used_at = last_used_at
        if last_ip is not None:
            db_row.last_ip = last_ip
        if status is not None:
            db_row.status = status
        s.add(db_row)
        s.commit()


def delete_token(token_id: int) -> bool:
    if _USING_TURSO:
        if not _run("SELECT id FROM ai_tokens WHERE id = ?", (token_id,)):
            return False
        _exec("DELETE FROM ai_tokens WHERE id = ?", (token_id,))
        return True
    with Session(_engine) as s:
        row = s.get(AIToken, token_id)
        if row:
            s.delete(row)
            s.commit()
            return True
        return False


# ============================================================
# Pending 连接相关（复用 key_server）
# ============================================================

def create_pending(connect_id: str, client_name: str, ip: str | None,
                   ua: str | None):
    if _USING_TURSO:
        now = dt.datetime.utcnow().isoformat()
        _exec(
            "INSERT INTO pending_connections (connect_id, client_name, ip, ua, status, created_at)"
            " VALUES (?, ?, ?, ?, 'pending', ?)",
            (connect_id, client_name, ip, ua, now),
        )
        rows = _run(
            "SELECT id, connect_id, client_name, ip, ua, status, created_at"
            " FROM pending_connections WHERE connect_id = ?", (connect_id,))
        return _row(rows[0])
    with Session(_engine) as s:
        row = PendingConnection(connect_id=connect_id, client_name=client_name, ip=ip, ua=ua)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def get_pending(connect_id: str):
    if _USING_TURSO:
        rows = _run(
            "SELECT id, connect_id, client_name, ip, ua, status, created_at"
            " FROM pending_connections WHERE connect_id = ?", (connect_id,))
        return _row(rows[0]) if rows else None
    with Session(_engine) as s:
        return s.exec(select(PendingConnection).where(
            PendingConnection.connect_id == connect_id)).first()


def list_pending() -> list:
    if _USING_TURSO:
        return [_row(r) for r in _run(
            "SELECT id, connect_id, client_name, ip, ua, status, created_at"
            " FROM pending_connections WHERE status = 'pending' ORDER BY created_at DESC")]
    with Session(_engine) as s:
        return list(s.exec(
            select(PendingConnection).where(PendingConnection.status == "pending")
            .order_by(PendingConnection.created_at.desc())).all())


def set_pending_status(pending_id: int, status: str) -> None:
    if _USING_TURSO:
        _exec("UPDATE pending_connections SET status = ? WHERE id = ?", (status, pending_id))
        return
    with Session(_engine) as s:
        row = s.get(PendingConnection, pending_id)
        if row:
            row.status = status
            s.add(row)
            s.commit()
