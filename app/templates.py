"""Inner HTML templates (Vercel deployment: templates are inlined, not file-based)."""
from __future__ import annotations
import json


def _esc(s):
    if s is None:
        return ""
    s = str(s)
    s = s.replace("&", "&")
    s = s.replace("<", "<")
    s = s.replace(">", ">")
    return s


def _iso(dt):
    return str(dt)[:19]


def make_dashboard_html(csrf_token: str, experiences, pending, tokens) -> str:
    data = {
        "experiences": [
            {
                "id": e.id,
                "title": e.title,
                "tags": e.tags,
                "project": e.project,
                "summary": e.summary or "",
                "created_at": _iso(e.created_at) if e.created_at else "",
                "updated_at": _iso(e.updated_at) if e.updated_at else "",
            }
            for e in (experiences or [])
        ],
        "pending": [
            {
                "id": p.id,
                "connect_id": p.connect_id,
                "client_name": p.client_name,
                "created_at": _iso(p.created_at) if p.created_at else "",
                "ip": p.ip or "",
            }
            for p in (pending or [])
        ],
        "tokens": [
            {
                "id": t.id,
                "client_name": t.client_name,
                "status": t.status,
                "created_at": _iso(t.created_at) if t.created_at else "",
                "expires_at": _iso(t.expires_at) if t.expires_at else "",
                "last_used_at": (_iso(t.last_used_at) if getattr(t, "last_used_at", None) else ""),
            }
            for t in (tokens or [])
        ],
    }
    init_js = json.dumps(data, ensure_ascii=False)
    csrf_hidden = '<input type="hidden" name="csrf_token" id="csrf-token" value="{}">'.format(_esc(csrf_token))
    e_cnt = str(len(experiences) if experiences else 0)
    p_cnt = str(len(pending) if pending else 0)
    t_cnt = str(len(tokens) if tokens else 0)

    return (
        '<!DOCTYPE html>'
        '<html lang="zh-CN">'
        '<head>'
        '    <meta charset="UTF-8">'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '    <title>Experience Library - 经验库</title>'
        '    <link rel="stylesheet" href="/static/style.css">'
        '    <script>'
        '        window.__DATA__ = ' + init_js + ';'
        '    </script>'
        '</head>'
        '<body>'
        '<h1 class="title">经验库</h1>'
        '<div class="wrap">'
        '    <section class="panel">'
        '        <h2>经验列表 <span id="experiences-count" class="count">(' + e_cnt + ')</span></h2>'
        '        <div class="search-bar">'
        '            <input type="text" id="search-keyword" placeholder="关键词（搜索标题/正文）">'
        '            <button id="search-btn">搜索</button>'
        '            <select id="filter-tag">'
        '                <option value="">全部标签</option>'
        '                <option value="vercel">vercel</option>'
        '                <option value="python">python</option>'
        '                <option value="fastapi">fastapi</option>'
        '                <option value="sqlmodel">sqlmodel</option>'
        '            </select>'
        '        </div>'
        '        <div id="exp-list"></div>'
        '    </section>'
        '    <section class="panel">'
        '        <h2>待审批连接 <span id="pending-count" class="count">(' + p_cnt + ')</span></h2>'
        '        <p class="hint">Agent 首次连接时出现在这里，点「同意」授权它获得 token。</p>'
        '        <div id="pending-list"></div>'
        '    </section>'
        '    <section class="panel">'
        '        <h2>已授权客户端 <span id="tokens-count" class="count">(' + t_cnt + ')</span></h2>'
        '        <div id="tokens-list"></div>'
        '    </section>'
        '    <button id="logout-btn" class="logout">退出登录</button>'
        '</div>'
        '<script src="/static/app.js?v=2"></script>'
        '</body>'
        '</html>'
    )


LOGIN_HTML = (
    '<!DOCTYPE html>'
    '<html lang="zh-CN">'
    '<head>'
    '    <meta charset="UTF-8">'
    '    <meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '    <title>Experience Library - 登录</title>'
    '    <link rel="stylesheet" href="/static/style.css">'
    '</head>'
    '<body>'
    '    <div class="card">'
    '        <h1>经验库</h1>'
    '        <p class="hint">输入登录密码</p>'
    '        <form id="login-form">'
    '            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">'
    '            <input type="password" name="password" placeholder="管理密码" autocomplete="current-password" required>'
    '            <button type="submit">登录</button>'
    '        </form>'
    '        <div id="err" class="err"></div>'
    '    </div>'
    '    <script src="/static/app.js?v=2"></script>'
    '</body>'
    '</html>'
)