"""项目上下文采集：把被开发后端项目的「历史文档 + 代码清单」汇总，作为 Agent 工作上下文。

仅读取、不改写。输出的文本会被 Orchestrator 注入到 ctx，使各阶段 Pod 能看到项目的
全部既有文档与代码结构 —— 对应核心需求：agent 根据【最新需求】+【项目历史所有文档】
去改后端项目代码。

项目根由 --project / AGENTS_PROJECT 指定（见 config.get_project_root）。
"""
import os
import re
import subprocess

from . import prompts


def collect_project_context(project_root, max_doc_chars=4000, max_files=300):
    """遍历 <root>/docs/**.md 与各代码文件，返回 {doc_count, file_count, docs_block, tree}。"""
    root = project_root
    doc_parts = []
    doc_count = 0
    docs_dir = os.path.join(root, "docs")
    if os.path.isdir(docs_dir):
        for dirpath, _d, files in os.walk(docs_dir):
            for fn in sorted(files):
                if not fn.lower().endswith(".md"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    text = open(p, encoding="utf-8").read()
                except Exception:
                    continue
                rel = os.path.relpath(p, root).replace("\\", "/")
                if len(text) > max_doc_chars:
                    text = text[:max_doc_chars].rstrip() + "\n…(文档过长已截断)"
                doc_parts.append(f"### 文档 {rel}\n{text}")
                doc_count += 1

    files = _list_code_files(root)[:max_files]
    tree = "\n".join(files) if files else "（无代码文件）"
    docs_block = "\n\n".join(doc_parts) if doc_parts else "（无 docs/ 文档）"
    return {"doc_count": doc_count, "file_count": len(files),
            "docs_block": docs_block, "tree": tree}


def _list_code_files(root):
    """返回项目代码文件相对路径清单；优先用 git ls-files，回退到目录遍历。"""
    if os.path.isdir(os.path.join(root, ".git")):
        try:
            out = subprocess.run(["git", "-C", root, "ls-files"],
                                 capture_output=True, text=True, timeout=20)
            if out.returncode == 0:
                files = [l for l in out.stdout.splitlines() if l.strip()]
                if files:
                    return files
        except Exception:
            pass
    skip = (".git", "__pycache__", "node_modules", ".agent_runs",
            ".workbuddy", "agent_runs", "requirements", ".obsidian")
    files = []
    for dp, ds, fs in os.walk(root):
        ds[:] = [d for d in ds if d not in skip]
        for fn in fs:
            if fn.endswith(".pyc"):
                continue
            files.append(os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/"))
    return sorted(files)


def build_project_context(project_root):
    """返回注入 ctx 的历史上下文文本块，以及采集统计。"""
    pc = collect_project_context(project_root)
    block = (
        "# 项目已有文档与代码（历史上下文，供本次任务参考；"
        "除非任务要求，勿修改这些既有文件）\n\n"
        f"## 项目文档（{pc['doc_count']} 篇）\n{pc['docs_block']}\n\n"
        f"## 项目代码文件清单（{pc['file_count']} 个）\n{pc['tree']}\n"
    )
    return block, pc


def slugify(title: str, max_len: int = 64) -> str:
    """把文档标题转成安全的文件名片段（保留中文与字母数字，其余转连字符）。"""
    s = (title or "").strip().lower()
    s = re.sub(r"[^\w.-]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-.")
    if not s:
        s = "doc"
    return s[:max_len]


def write_project_doc(project_root, doc_text):
    """把一篇已通过 doclint 的文档写回 <project>/docs/<slug>.md（历史增厚）。

    返回 {"status": "written"|"skipped"|"failed", "path", "reason", "feedback"}：
      - written : 成功写入新文档
      - skipped : 目标已存在，跳过写回以避免覆盖既有文档（历史增厚以新增为主）
      - failed  : 落库后 doclint 复校不通过（已删除脏文件），需 agent 重做改稿
    """
    from .doclint_check import DocLint

    fm, _ = prompts.parse_frontmatter(doc_text)
    if not fm or not fm.get("title"):
        return {"status": "failed", "reason": "文档缺少 frontmatter/title，无法推导落库路径",
                "path": None, "feedback": "请在文档开头提供合法 frontmatter，并至少包含 title。"}
    slug = fm.get("slug") or slugify(fm.get("title"))
    docs_dir = os.path.join(project_root, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    target = os.path.join(docs_dir, slug + ".md")
    # 双保险：slugify 已清洗，这里再校验真实路径仍在项目 docs 内，防止越界写文件
    if not os.path.realpath(target).startswith(os.path.realpath(docs_dir) + os.sep):
        return {"status": "failed", "reason": "推导出的落库路径越过项目 docs 目录",
                "path": None, "feedback": "请检查文档 title/slug 是否含非法路径片段。"}
    if os.path.exists(target):
        return {"status": "skipped", "reason": "文档已存在，跳过写回以避免覆盖",
                "path": target, "feedback": ""}
    with open(target, "w", encoding="utf-8") as f:
        f.write(doc_text)
    # 落库后用磁盘真实路径复校（wikilink 基准以真实目录为准，比内存校验更准）
    lint = DocLint().validate_path(target)
    if not lint.ok:
        try:
            os.remove(target)
        except OSError:
            pass
        return {"status": "failed", "reason": "落库后 doclint 复校不通过",
                "path": target, "feedback": lint.feedback}
    return {"status": "written", "path": target, "feedback": ""}
