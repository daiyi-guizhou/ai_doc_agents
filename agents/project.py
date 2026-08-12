"""项目上下文采集：把被开发后端项目的「历史文档 + 代码清单」汇总，作为 Agent 工作上下文。

仅读取、不改写。输出的文本会被 Orchestrator 注入到 ctx，使各阶段 Pod 能看到项目的
全部既有文档与代码结构 —— 对应核心需求：agent 根据【最新需求】+【项目历史所有文档】
去改后端项目代码。

项目根由 --project / AGENTS_PROJECT 指定（见 config.get_project_root）。
"""
import os
import subprocess


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
