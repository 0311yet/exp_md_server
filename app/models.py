"""SQLModel 数据模型。

经验库的核心实体是 Experience（一条经验 = 一个 MD 文件，body_md 存全文，
frontmatter 解析后的元数据存单独字段以便检索/筛选）。
auth 相关表沿袭 key_server：settings / ai_tokens / pending_connections。
"""
from __future__ import annotations
import datetime as dt
from typing import Optional

from sqlmodel import SQLModel, Field


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


class Experience(SQLModel, table=True):
    """一条经验。Agent 上传的 MD 解析后存这里。

    title/tags/project 由 frontmatter 提取；body_md 是去掉 frontmatter 的正文。
    单条经验不可太大（经验文档一般 < 50KB），直接存数据库。
    """
    __tablename__ = "experiences"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)                 # frontmatter.title（必填）
    tags: str = Field(default="")                  # frontmatter.tags，逗号分隔，便于 LIKE 筛选
    project: str = Field(default="", index=True)   # frontmatter.project
    body_md: str                                    # 去 frontmatter 的正文
    raw_md: str                                     # 原始上传内容（含 frontmatter），供 Agent 原样下载
    summary: str = Field(default="")               # frontmatter.summary（可选），列表展示用
    created_at: dt.datetime = Field(default_factory=_now)
    updated_at: dt.datetime = Field(default_factory=_now)


class AIToken(SQLModel, table=True):
    """已授权 Agent 的 token。只存 hash，不存明文。"""
    __tablename__ = "ai_tokens"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_name: str = Field(index=True)
    token_hash: str = Field(index=True, unique=True)
    status: str = Field(default="approved")  # approved / revoked
    created_at: dt.datetime = Field(default_factory=_now)
    expires_at: dt.datetime
    last_used_at: Optional[dt.datetime] = Field(default=None)
    last_ip: Optional[str] = Field(default=None)


class PendingConnection(SQLModel, table=True):
    """待审批的 Agent 连接申请。"""
    __tablename__ = "pending_connections"

    id: Optional[int] = Field(default=None, primary_key=True)
    connect_id: str = Field(index=True, unique=True)
    client_name: str
    created_at: dt.datetime = Field(default_factory=_now)
    ip: Optional[str] = Field(default=None)
    ua: Optional[str] = Field(default=None)
    status: str = Field(default="pending")


class Setting(SQLModel, table=True):
    """通用键值表，存密码哈希之类。"""
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: str
