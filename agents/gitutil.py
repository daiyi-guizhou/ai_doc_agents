"""项目 Git 工具：为被开发的后端项目提供安全网与可审计的着陆。

设计原则（安全优先，绝不自动 push 主干）：
- checkpoint：任务开始前，在当前 git 仓库从 HEAD 切出新分支 agent-<jobid>，
  后续 developer/tester 的全部改动都发生在该分支上，原分支（main/master）保持干净。
- commit：任务 done 后在 agent 分支上提交改动（不 push）。
- REVIEW.md + merge_to_main / rollback：提供人工 review 闸门——默认不合并，
  由人类显式 approve 才 merge 回主干并删分支；rollback 则丢弃分支与改动。
- 非 git 仓库（或环境变量 AGENTS_NO_GIT=1）则全部降级为 no-op（kind="none"），
  不影响「文档驱动」闭环本身。
"""
import os
import subprocess


def _disabled():
    return os.environ.get("AGENTS_NO_GIT") == "1"


def _run(root, args, timeout=60):
    try:
        p = subprocess.run(["git", "-C", root] + args, capture_output=True,
                           text=True, timeout=timeout, shell=False)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:  # 任意异常都降级为可控错误，避免卡死编排
        return -1, "", str(e)


def is_git_repo(root):
    rc, _, _ = _run(root, ["rev-parse", "--is-inside-work-tree"])
    return rc == 0


def current_branch(root):
    rc, out, _ = _run(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if rc == 0 else None


def head_commit(root):
    rc, out, _ = _run(root, ["rev-parse", "HEAD"])
    return out.strip() if rc == 0 else None


def _primary_branch(root):
    """返回仓库主干分支名：优先 master，其次 main，都没有则退回当前分支。"""
    for name in ("master", "main"):
        rc, out, _ = _run(root, ["rev-parse", "--verify", f"refs/heads/{name}"])
        if rc == 0 and out.strip():
            return name
    return current_branch(root)


def checkpoint(root, job_id):
    """在 project 上建立安全检查点：从主干切出 agent-<jobid> 分支（主干保持干净）。

    始终基于主干（master/main）切分支，避免因上次失败运行把仓库留在某个
    agent 分支上而导致 agent 分支嵌套；强制切回主干也会丢弃上次遗留的未提交改动。
    """
    if _disabled() or not is_git_repo(root):
        return {"ok": True, "kind": "none", "branch": None,
                "base_commit": None, "base_branch": None}
    base_branch = _primary_branch(root)
    # 强制切回主干（丢弃可能存在的上次失败遗留改动），保证 agent 分支从主干拉出
    _run(root, ["checkout", "-f", base_branch])
    base_commit = head_commit(root)
    branch = f"agent-{job_id}"
    _run(root, ["branch", "-D", branch])          # 重跑时清掉旧分支
    rc, _, err = _run(root, ["checkout", "-b", branch])
    if rc != 0:
        return {"ok": False, "kind": "git", "branch": None,
                "base_commit": base_commit, "base_branch": base_branch,
                "error": err.strip()}
    return {"ok": True, "kind": "git", "branch": branch,
            "base_commit": base_commit, "base_branch": base_branch}


def restore(root, base_branch):
    """失败时把工作树强制还原回主干（丢弃 agent 分支上的未提交改动）；agent 分支保留供排查。"""
    if not base_branch:
        return {"ok": False, "error": "无 base_branch"}
    rc, _, err = _run(root, ["checkout", "-f", base_branch])
    return {"ok": rc == 0, "error": (err.strip() if rc != 0 else "")}


def commit(root, message):
    """在当前分支提交所有改动（不 push）。"""
    rc, _, err = _run(root, ["add", "-A"])
    if rc != 0:
        return {"ok": False, "error": err.strip()}
    rc, out, err = _run(root, ["commit", "-m", message])
    if rc != 0:
        if "nothing to commit" in (err + out):
            return {"ok": True, "commit": head_commit(root), "empty": True}
        return {"ok": False, "error": err.strip()}
    return {"ok": True, "commit": head_commit(root)}


def diff_stat(root, base_commit):
    if base_commit:
        rc, out, _ = _run(root, ["diff", "--stat", f"{base_commit}...HEAD"])
    else:
        rc, out, _ = _run(root, ["show", "--stat", "HEAD"])
    return out if rc == 0 else ""


def changed_files(root, base_commit):
    if base_commit:
        rc, out, _ = _run(root, ["diff", "--name-only", f"{base_commit}...HEAD"])
    else:
        rc, out, _ = _run(root, ["show", "--name-only", "--oneline", "HEAD"])
    return [l for l in out.splitlines() if l.strip()] if rc == 0 else []


def merge_to_main(root, branch, base_branch):
    """人工 review 通过：把 agent 分支合并回主干并删除分支（不 push）。"""
    rc, _, err = _run(root, ["checkout", base_branch])
    if rc != 0:
        return {"ok": False, "error": f"切回主干失败: {err.strip()}"}
    rc, _, err = _run(root, ["merge", "--no-ff", branch, "-m",
                             f"merge {branch} into {base_branch} (human approved)"])
    if rc != 0:
        _run(root, ["merge", "--abort"])
        return {"ok": False, "error": f"合并冲突，已 abort：{err.strip()}"}
    _run(root, ["branch", "-d", branch])
    return {"ok": True}


def rollback(root, branch, base_branch):
    """丢弃 agent 分支及其改动，回到主干（人工拒绝时使用）。"""
    _run(root, ["checkout", base_branch])
    rc, _, err = _run(root, ["branch", "-D", branch])
    return {"ok": rc == 0, "error": (err.strip() if rc != 0 else "")}
