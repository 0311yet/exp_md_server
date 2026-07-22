# Experience Library（经验库）

云端经验沉淀系统：**Web 页面 + API**，供人管理 + Agent 上传下载。

- **人**（Web）：登录 → 浏览经验列表 → 搜索/筛选 → **删除**经验 + **审批/吊销** Agent 连接
- **Agent**（API）：敲门 → 等待人审批 → Bearer token → **上传/下载/修改**经验 MD（不能删除）

技术栈：FastAPI + Turso (libSQL) / SQLite 降级 + Vercel Serverless

---

## 快速开始

### 本地开发

```bash
pip install -r requirements.txt
cp .env.example .env    # 填 LOGIN_PASSWORD 和 SESSION_SECRET
uvicorn app.main:app --reload --port 8000
# 访问 http://localhost:8000
```

### 部署到 Vercel + Turso

#### 1. 创建 Turso 数据库

```bash
# 安装 turso CLI
curl -sSfL https://get.tur.so/install.sh | bash

# 创建数据库
turso db create exp-md-server
turso db show exp-md-server --url          # 复制到 TURSO_DATABASE_URL
turso db tokens create exp-md-server        # 复制到 TURSO_AUTH_TOKEN
```

#### 2. Vercel 部署

```bash
# 在 Vercel Dashboard 新建项目，关联 GitHub repo
# Settings → Environment Variables 填入：
#   LOGIN_PASSWORD       → 你的管理密码
#   SESSION_SECRET       → openssl rand -hex 32
#   TURSO_DATABASE_URL   → libsql://xxx.turso.io
#   TURSO_AUTH_TOKEN     → eyJhbGci...
git push   # 自动触发部署
```

---

## 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `LOGIN_PASSWORD` | Web 管理密码 | `your-strong-password` |
| `SESSION_SECRET` | session cookie 签名密钥 | `openssl rand -hex 32` |
| `TURSO_DATABASE_URL` | Turso 数据库 URL（部署到 Vercel 时必填，不填则走本地 SQLite） | `libsql://your-db.turso.io` |
| `TURSO_AUTH_TOKEN` | Turso 认证 token | `eyJhbGci...` |
| `DB_FILE` | 本地 SQLite 路径（可选，默认 `data/exp_md.db`） | `data/exp_md.db` |

**本地开发**：`TURSO_DATABASE_URL` 不填，自动使用 SQLite  
**Vercel 部署**：`TURSO_DATABASE_URL` 必填，走 Turso HTTP API（无状态，适合 Serverless）

---

## API 概览

### AI 连接（敲门→审批→token）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/connect` | Agent 敲门，Body: `client_name` |
| `GET` | `/api/connect/{connect_id}/status` | 轮询审批状态，`approved` 时返回 `token` |

### 经验 CRUD（需 Bearer token）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/experiences` | 列表，支持 `?keyword=...&tag=...&project=...` |
| `GET` | `/api/experiences/{id}` | 获取完整经验（含 raw_md） |
| `POST` | `/api/experiences` | 上传（Body: `raw_md`，必需含 frontmatter + title） |
| `PUT` | `/api/experiences/{id}` | 修改（整体替换） |

### Web 专属（需登录 session）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/dashboard/delete_experience` | 删除经验（Form: `exp_id`） |
| `POST` | `/dashboard/delete_token` | 吊销 Agent token（Form: `token_id`） |
| `POST` | `/connect/{connect_id}/approve` | 同意 Agent 连接 |
| `POST` | `/connect/{connect_id}/deny` | 拒绝 Agent 连接 |

---

## 一条经验的格式

MD 文件必须以 YAML frontmatter 开头：

```markdown
---
title: 简短具体的一句话标题（必填）
tags: vercel, python, serverless
project: key_server
summary: 一句话概述根因+解决方案
---

## 问题
<复现现象>

## 根因
<为什么发生>

## 解决方案
<具体步骤>

## 教训 / 复用提示
<一句话避坑>
```

---

## Agent 授权流程（首次）

1. Agent 调用 `scripts/exp_client.py`
2. 自动 POST `/api/connect`，拿到 `connect_id`
3. 在浏览器打开 `/dashboard` → 登录 → 在「待审批连接」点「同意」
4. Agent 轮询到 `approved` → 自动保存 token 到 `scripts/.explib_token`
5. 后续调用无需再审批，token 30 天有效（剩余 <7 天自动续期）

---

## 目录结构

```
exp_md_server/
├── app/
│   ├── main.py       # 所有路由（Web + AI API）
│   ├── auth.py       # Session + Bearer token 认证
│   ├── db.py         # Turso / SQLite 双模式
│   ├── models.py     # 数据模型
│   ├── config.py     # 环境变量
│   ├── mdparse.py    # frontmatter 解析
│   └── templates.py  # 内联 Jinja2 模板
├── public/           # 静态文件（Vercel CDN 自动服务）
│   ├── app.js
│   └── style.css
├── api/index.py      # Vercel 入口
├── vercel.json
├── requirements.txt
└── .env.example
```

---

## Vercel 架构说明

```
请求 /static/app.js
    → vercel.json rewrite: /static/(.*) → /public/$1
    → public/app.js（CDN 缓存，零 Python 开销）

请求 /api/experiences
    → vercel.json rewrite: /(.*) → /api/index
    → api/index.py → app/main.py → Turso HTTP API
```

- **静态文件**（CSS/JS）：Vercel CDN 直接服务，无冷启动
- **API 请求**：FastAPI 处理，走 Turso HTTP API（`libsql://`）
- **无状态**：每个函数实例独立，Turso 提供共享数据库