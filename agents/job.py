"""Job：一次任务的状态机与产物落库。

产物写入项目根 agent_runs/<jobid>/（独立于 docs 治理，由 .gitignore 忽略）：
  - NN-<role>.md      每个阶段的产出
  - state.json        进度/状态机快照
  - SUMMARY.md        全文汇总，便于人类回看
"""
import json
import os
import uuid
from datetime import datetime


class Job:
    def __init__(self, requirement: str, runs_root: str = "agent_runs",
                 with_sandbox: bool = True, project_root: "str | None" = None):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.job_id = f"{stamp}-{str(uuid.uuid4())[:4]}"
        self.requirement = requirement
        self.state = "running"  # running | done | failed
        self.error = None
        self.stages = []        # [{idx, label, role, ts, output}]
        self.log = []           # 过程日志（含回退记录）
        self.project_root = project_root   # 被开发的后端项目根（可能为 None）
        self.git = None         # git 检查点信息（orchestrator 填充）
        self.created = datetime.now().isoformat(timespec="seconds")
        self.dir = os.path.join(runs_root, self.job_id)
        os.makedirs(self.dir, exist_ok=True)
        # 沙箱根：若绑定后端项目 → 沙箱即项目目录（developer/tester 真实改项目、跑项目测试）；
        # 否则用任务私有沙箱（agent_runs/<jobid>/sandbox）。agent_runs/<jobid>/ 始终仅作只读记录。
        from .sandbox import Sandbox
        if not with_sandbox:
            self.sandbox_root = None
            self.sandbox = None
        elif project_root:
            self.sandbox_root = project_root
            self.sandbox = Sandbox(project_root)
        else:
            self.sandbox_root = os.path.join(self.dir, "sandbox")
            self.sandbox = Sandbox(self.sandbox_root)

    def record(self, idx: int, label: str, role: str, output: str):
        self.stages.append({
            "idx": idx, "label": label, "role": role,
            "ts": datetime.now().isoformat(timespec="seconds"), "output": output,
        })
        self._write_product(idx, label, role, output)

    def _write_product(self, idx: int, label: str, role: str, output: str):
        fname = f"{idx:02d}-{role}.md"
        with open(os.path.join(self.dir, fname), "w", encoding="utf-8") as f:
            f.write(f"# {label} · {role}\n\n{output}\n")

    def note(self, msg: str):
        ts = datetime.now().isoformat(timespec="seconds")
        self.log.append(f"[{ts}] {msg}")

    def done(self):
        self.state = "done"

    def fail(self, reason: str):
        self.state = "failed"
        self.error = reason
        self.note(f"任务失败：{reason}")

    def save(self):
        state = {
            "job_id": self.job_id,
            "requirement": self.requirement,
            "state": self.state,
            "error": self.error,
            "created": self.created,
            "project_root": self.project_root,
            "git": self.git,
            "stages": [
                {k: s[k] for k in ("idx", "label", "role", "ts")} for s in self.stages
            ],
            "log": self.log,
        }
        with open(os.path.join(self.dir, "state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        with open(os.path.join(self.dir, "SUMMARY.md"), "w", encoding="utf-8") as f:
            f.write(f"# Job {self.job_id}\n\n")
            f.write(f"> 需求：{self.requirement}\n\n")
            f.write(f"> 状态：**{self.state}**\n\n---\n\n")
            for s in self.stages:
                f.write(f"## {s['idx']:02d}. {s['label']} · {s['role']}\n\n")
                f.write(f"{s['output']}\n\n")
        return self.dir
