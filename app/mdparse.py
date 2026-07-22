"""MD 经验文件的 frontmatter 解析。

约定一条经验的格式：
    ---
    title: Vercel Python 冷启动超时
    tags: vercel, python, serverless
    project: key_server
    summary: 冷启动超时的根因和优化手段
    ---
    ## 问题
    ...
    ## 解决方案
    ...

本模块只做最小可用解析：
- 提取 frontmatter 里 title / tags / project / summary 四个字段
- tags 支持逗号分隔或 YAML 列表两种写法
- frontmatter 必须在文件开头，首行必须是 `---`
- 不依赖 PyYAML，避免给 Vercel 加额外依赖
"""
from __future__ import annotations
import re


_REQUIRED_FIELDS = ("title",)


def parse_markdown(raw: str) -> tuple[dict, str]:
    """解析经验 MD，返回 (frontmatter_dict, body_md)。

    若无 frontmatter 或 title 缺失，frontmatter_dict 为空字典，
    body_md 退化为原始全文（由调用方决定要不要拒绝）。
    """
    if not raw or not raw.lstrip().startswith("---"):
        return {}, raw

    # 找首尾 ---
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, raw

    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:]).lstrip("\n")

    fm: dict = {}
    for line in fm_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1).lower()
        val = m.group(2).strip()
        # 去 YAML 列表 ["a","b"] 写法
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            val = ",".join(p.strip().strip("\"'") for p in inner.split(",") if p.strip())
        fm[key] = val

    return fm, body


def extract_experience_fields(raw: str) -> tuple[str, str, str, str, str] | None:
    """从原始 MD 提取经验字段。返回 (title, tags, project, summary, body_md)。

    无 title 返回 None。
    """
    fm, body = parse_markdown(raw)
    title = fm.get("title", "").strip()
    if not title:
        return None
    tags = fm.get("tags", "").strip()
    project = fm.get("project", "").strip()
    summary = fm.get("summary", "").strip()
    return title, tags, project, summary, body
