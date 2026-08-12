"""Orchestrator 总控：作为 LLM agent 动态决定下一阶段，直到任务「干好」。

与旧版「固定管线」的区别：
  - 旧版：requirement-analyst → … → retrospector 写死，门禁 FAIL 才回退。
  - 新版：Orchestrator 自身是一个 LLM agent，每轮读取累积上下文 + 上一阶段门禁结果，
         输出一个决策（next / rollback / done + role），由模型决定走向，而非固定顺序。
         Mock 模式用确定性状态机兜底，行为等价于旧管线（保证离线可验证）。

七阶段（角色目录 + 兜底顺序）：
  requirement-analyst 需求分析 / system-designer 概要设计 / developer 开发 /
  tester 测试 / deployer 部署 / verifier 验证 / retrospector 复盘

安全网（无论模型如何决定都生效）：
  - 门禁阶段（tester/deployer/verifier）FAIL → 回退到 developer 重做。
  - 模型请求 done 前，必须已有一次 验证 PASS，否则强制重跑验证。
  - MAX_ITER 上限防死循环；超次判定任务失败。
"""
import re

from . import prompts
from .llm import MockLLM

# 七个阶段（role, 中文标签）——作为角色目录与兜底顺序
STAGES = [
    ("requirement-analyst", "需求分析"),
    ("system-designer", "概要设计"),
    ("developer", "开发"),
    ("tester", "测试"),
    ("deployer", "部署"),
    ("verifier", "验证"),
    ("retrospector", "复盘"),
]
ROLE_LABEL = dict(STAGES)
ORDER = [r for r, _ in STAGES]
GATE_ROLES = {"tester", "deployer", "verifier"}   # 门禁阶段
ROLLBACK_TARGET = "developer"                       # 门禁失败回退点
MAX_ITER = 16

# 拥有真实执行能力（沙箱）的角色
SANDBOX_ROLES = {"developer", "tester"}

# 决策协议：模型在产出中给出恰好一个 decision 块
DECISION_FENCE = re.compile(r"```decision\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_DECISION_INSTR = """\
# 动态决策协议
你来决定下一个要执行的阶段（不是固定顺序）。我会把累积上下文、上一阶段产出与门禁结果给你，
你必须输出**恰好一个**决策，用如下 fenced 块：

```decision
{"action": "next", "role": "developer"}
```

action 取值：
- "next"    : 执行 role 阶段（普通推进，或重做某阶段皆可）
- "rollback": 回退到 role 阶段重做（门禁失败时使用）
- "done"    : 任务已完成（须先确保『验证 PASS』且『复盘完成』）

约束：
- role 必须取自：requirement-analyst / system-designer / developer / tester / deployer / verifier / retrospector
- 必须向『验证通过 + 复盘完成』收敛，禁止无意义地重复同一阶段
- 门禁阶段（tester/deployer/verifier）若上次为 FAIL，应 rollback 到 developer 重做
只输出该 decision 块，不要多余解释。"""


class Orchestrator:
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.llm = getattr(scheduler, "llm", None)
        # 决策 system prompt 来自本地文档（SSOT）：docs/agents/orchestrator.md
        try:
            self._base_prompt = prompts.load_role("orchestrator")["prompt"]
        except Exception:
            self._base_prompt = "你是多 Agent 系统的总控编排者，负责决定下一阶段。"

    def _task_for(self, label: str, role: str, requirement: str, redo: bool = False) -> str:
        head = "（重做）" if redo else ""
        return (
            f"你是本次任务的【{label}】阶段负责人（角色：{role}）{head}。\n"
            f"原始需求：{requirement}\n\n"
            f"请基于上方『任务上下文』中的前序产出，完成本阶段交付物；"
            f"要求具体、可执行、可被下一阶段直接消费。\n"
            f"若本阶段为『验证』，请在开头明确给出 PASS 或 FAIL 判定及理由；"
            f"若为『测试/部署』，请在开头给出 通过 / 失败 结论。"
        )

    @staticmethod
    def _gate(label: str, output: str) -> bool:
        """判定某阶段是否通过。非门禁阶段默认通过。"""
        head = output.strip().upper()
        if label == "验证":
            low = output.lower()
            if "fail" in low and "pass" not in low:
                return False
            if head.startswith("FAIL"):
                return False
            return True
        if head.startswith("FAIL") or "【失败】" in output or "失败：" in output[:40]:
            return False
        return True

    @staticmethod
    def _gate_str(ok):
        if ok is None:
            return "无（非门禁阶段）"
        return "PASS" if ok else "FAIL"

    # ---------------- 决策：真实 LLM ----------------
    def _decide(self, requirement, ctx, last_role, last_output, last_gate_ok):
        summary = ctx[-4000:]
        last_name = ROLE_LABEL.get(last_role, last_role) if last_role else "（首次）"
        user = (
            f"原始需求：{requirement}\n\n"
            f"当前任务上下文（最近片段）：\n{summary}\n\n"
            f"上一阶段：{last_name}（{last_role or '无'}）\n"
            f"当前门禁判定（仅指上一阶段）：{self._gate_str(last_gate_ok)}\n"
            f"上一阶段产出片段：\n{last_output[:1200]}\n\n"
            f"请输出下一步决策（仅一个 ```decision 块）。"
        )
        text = self.llm.complete(system=self._base_prompt + "\n\n" + _DECISION_INSTR, user=user)
        return self._parse_decision(text)

    @staticmethod
    def _parse_decision(text):
        m = DECISION_FENCE.search(text or "")
        if not m:
            return None
        import json
        try:
            d = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            return None
        if not isinstance(d, dict) or d.get("action") not in ("next", "rollback", "done"):
            return None
        role = d.get("role")
        if d["action"] != "done" and role not in ORDER:
            return None
        return d

    # ---------------- 决策：Mock 状态机（等价于旧管线 + 回退） ----------------
    @staticmethod
    def _mock_decide(last_role, last_gate_ok, pos):
        if last_role is None:
            return "next", ORDER[0]
        if last_role == "retrospector":
            return "done", None
        if last_role in GATE_ROLES and last_gate_ok is False:
            return "rollback", ROLLBACK_TARGET
        npos = (pos + 1) if pos >= 0 else 0
        return "next", ORDER[npos]

    @staticmethod
    def _fallback(last_role, last_gate_ok, pos):
        if last_role in GATE_ROLES and last_gate_ok is False:
            return "rollback", ROLLBACK_TARGET
        if last_role == "retrospector":
            return "done", None
        npos = (pos + 1) if pos >= 0 else 0
        if npos < len(ORDER):
            return "next", ORDER[npos]
        return "done", None

    # ---------------- 主循环 ----------------
    def run(self, requirement: str, use_sandbox: bool = True) -> "Job":
        from .job import Job
        job = Job(requirement, with_sandbox=use_sandbox)
        job.note("Orchestrator(LLM-agent) 启动，需求：" + requirement)
        if use_sandbox:
            job.note("沙箱已启用：developer/tester 将真实读写文件、跑命令")
        if isinstance(self.llm, MockLLM):
            job.note("决策来源：Mock 状态机（离线兜底，等价于固定管线）")
        else:
            job.note("决策来源：LLM 动态决策（docs/agents/orchestrator.md 为策略提示词）")

        ctx = f"原始需求：{requirement}\n"
        last_role = None
        last_gate_ok = None
        last_output = ""
        pos = -1
        seq = 0
        verify_passed = False
        iters = 0

        while True:
            iters += 1
            if iters > MAX_ITER:
                job.fail(f"超过最大迭代次数({MAX_ITER})，任务未收敛")
                break

            # 1) 决策
            if isinstance(self.llm, MockLLM):
                action, role = self._mock_decide(last_role, last_gate_ok, pos)
            else:
                dec = self._decide(requirement, ctx, last_role, last_output, last_gate_ok)
                if dec is None:
                    job.note("决策解析失败，启用兜底逻辑")
                    action, role = self._fallback(last_role, last_gate_ok, pos)
                else:
                    action, role = dec["action"], dec.get("role")

            # 2) 安全网：门禁 FAIL 强制回退，覆盖模型决策（确保「活干好」）
            if last_role in GATE_ROLES and last_gate_ok is False:
                action, role = "rollback", ROLLBACK_TARGET
                job.note("门禁 FAIL，强制回退到开发重做（覆盖模型决策）")

            # 3) 质量闸门：done 前必须验证通过
            if action == "done":
                if not verify_passed:
                    job.note("请求 done 但验证尚未 PASS，强制重跑验证")
                    action, role = "next", "verifier"
                else:
                    break  # 任务完成

            # 4) 非法角色兜底
            if role not in ORDER:
                job.note(f"决策角色非法：{role}，启用兜底")
                action, role = self._fallback(last_role, last_gate_ok, pos)

            # 5) 执行该阶段 Pod
            label = ROLE_LABEL[role]
            redo = (action == "rollback")
            pod = self.scheduler.spawn(role)
            sandbox = job.sandbox if role in SANDBOX_ROLES else None
            try:
                output = pod.run(
                    task=self._task_for(label, role, requirement, redo=redo),
                    context=ctx, sandbox=sandbox,
                )
            finally:
                self.scheduler.destroy(pod)

            job.record(seq, label, role, output)
            seq += 1
            ctx += f"\n## {label}（{role}）产出\n{output}\n"
            job.note(f"阶段完成：{label}（{role}）" + (" [回退重做]" if redo else ""))

            # 6) 门禁判定，回填决策上下文
            if role in GATE_ROLES:
                last_gate_ok = self._gate(label, output)
                verdict = "PASS" if last_gate_ok else "FAIL"
                ctx += f"（门禁判定：{verdict}）\n"
                if role == "verifier" and last_gate_ok:
                    verify_passed = True
                job.note(f"{label} 门禁：{verdict}")
                if not last_gate_ok:
                    job.note(f"{label} 未通过，将回退到 {ROLE_LABEL[ROLLBACK_TARGET]} 重做")
            else:
                last_gate_ok = None

            last_role = role
            pos = ORDER.index(role)
            last_output = output

        if job.state == "running":
            job.done()
            job.note("验证通过且复盘完成，任务『活干好』✓")

        job.save()
        return job
