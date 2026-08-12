"""提示词仓库：从本地文档 docs/agents/<role>.md 加载 Agent 的系统提示词。

文档即配置（SSOT）：每篇角色文档的 frontmatter + 正文 = 该角色的 system prompt。
复用与 doclint 一致的极简 frontmatter 解析，避免引入额外依赖。
"""
import os

AGENTS_DIR = os.path.join("docs", "agents")
EXEMPT = {"README.md", "_template.md"}


def parse_frontmatter(text):
    """返回 (data_dict, body_text)。无合法 frontmatter 时 (None, text)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, text
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])
    data = {}
    for line in fm_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        data[key.strip()] = val.strip().strip("\"'")
    return data, body


def load_role(role: str) -> dict:
    """加载某角色文档，返回 {role, title, owner, prompt, meta}。"""
    path = os.path.join(AGENTS_DIR, f"{role}.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f"角色文档不存在: {path}（请在 docs/agents/ 下创建）")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fm, body = parse_frontmatter(text)
    meta = fm or {}
    return {
        "role": role,
        "title": meta.get("title", role),
        "owner": meta.get("owner", "AI"),
        "prompt": body.strip(),
        "meta": meta,
    }


def list_roles():
    """列出所有可用角色名（排除索引与模板）。"""
    if not os.path.isdir(AGENTS_DIR):
        return []
    return sorted(
        p[:-3] for p in os.listdir(AGENTS_DIR)
        if p.endswith(".md") and p not in EXEMPT
    )
