"""Orchestrator 总控：作为 LLM agent 动态决定下一阶段，直到任务「干好」。

与旧版「固定管线」的区别：
  - 旧版：requirement-analyst → … → retrospector 写死，门禁 FAIL 才回退。
  - 新版：Orchestrator 自身是一个 LLM agent，每轮读取累积上下文 + 上一阶段门禁结果，
         输出一个决策（next / rollback / done + role），由模型决定走向，而非固定顺序。
         Mock 模式用确定性状态机兜底，行为等价于旧管线（保证离线可验证）。

七阶段（角色目录 + 兜底顺序，--doc 时于概要设计后插入 documenter）：
  requirement-analyst 需求分析 / system-designer 概要设计 /
  documenter 文档撰写(可选) / developer 开发 /
  tester 测试 / deployer 部署 / verifier 验证 / retrospector 复盘

安全网（无论模型如何决定都生效）：
  - 文档校验闸门：documenter 产出须过 doclint（frontmatter/type/status/死链），
    error 级即 FAIL → 退回 documenter 重做并附反馈，连续超 DOCLINT_MAX_RETRY 判失败。
  - 门禁阶段（tester/deployer/verifier）FAIL → 回退到 developer 重做。
  - 模型请求 done 前，必须已有一次 验证 PASS，否则强制重跑验证。
  - MAX_ITER 上限防死循环；超次判定任务失败。
"""
import re

from . import prompts
from .llm import MockLLM

# 基础阶段（不含文档撰写）；run(doc=True) 时于 system-designer 后插入 documenter
BASE_STAGES = [
    ("requirement-analyst", "需求分析"),
    ("system-designer", "概要设计"),
    ("developer", "开发"),
    ("tester", "测试"),
    ("deployer", "部署"),
    ("verifier", "验证"),
    ("retrospector", "复盘"),
]
DOC_STAGE = ("documenter", "文档撰写")   # 写文档的 agent：产出须经 doclint 闸门

# 模块级默认（无 --doc），供 CLI/工具直接引用
STAGES = BASE_STAGES
ROLE_LABEL = dict(STAGES)
ORDER = [r for r, _ in STAGES]

GATE_ROLES = {"tester", "deployer", "verifier"}   # 门禁阶段
ROLLBACK_TARGET = "developer"                       # 门禁失败回退点
MAX_ITER = 16

# 拥有真实执行能力（沙箱）的角色
SANDBOX_ROLES = {"developer", "tester"}

# 文档治理闸门：这些角色的产出须经 doclint 校验，不通过则退回重做
DOCLINT_ROLES = {"documenter"}
DOCLINT_MAX_RETRY = 3        # 连续不通过上限，超过判任务失败

# 决策协议：模型在产出中给出恰好一个 decision 块
DECISION_FENCE = re.compile(r"```decision\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_DECISION_INSTR = """\
# 动态决策协议
你来决定下一个要执行的阶段（不是固定顺序）。我会把累积上下文、上一阶段产出与门禁结果给你，
你必须输出**恰好一个**决策，用如下 fenced 块：

```decision
{"action": "next", "role": "system-designer"}
```

action 取值：
- "next"    : 执行 role 阶段（普通推进，或重做某阶段皆可）
- "rollback": 回退到 role 阶段重做（门禁失败时使用）
- "done"    : 任务已完成（须先确保『验证 PASS』且『复盘完成』）

约束：
- role 必须取自：{roles}
- 必须向『验证通过 + 复盘完成』收敛，禁止无意义地重复同一阶段
- 门禁阶段（tester/deployer/verifier）若上次为 FAIL，应 rollback 到 developer 重做
- 写文档阶段（documenter）若上次文档校验 FAIL，应 redo documenter 并参考反馈改稿

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

    # ---------------- 阶段装配 ----------------
    @staticmethod
    def _build_stages(doc: bool):
        """装配本次任务使用的阶段顺序；doc=True 时在概要设计后插入文档撰写。"""
        stages = list(BASE_STAGES)
        if doc:
            i = next(idx for idx, (r, _) in enumerate(stages) if r == "system-designer")
            stages.insert(i + 1, DOC_STAGE)
        return stages

    @staticmethod
    def _build_decision_instr(order):
        return _DECISION_INSTR.format(roles=" / ".join(order))

    # ---------------- 决策：真实 LLM ----------------
    def _decide(self, requirement, ctx, last_role, last_output, last_gate_ok, order, role_label):
        summary = ctx[-4000:]
        last_name = role_label.get(last_role, last_role) if last_role else "（首次）"
        user = (
            f"原始需求：{requirement}\n\n"
            f"当前任务上下文（最近片段）：\n{summary}\n\n"
            f"上一阶段：{last_name}（{last_role or '无'}）\n"
            f"当前门禁判定（仅指上一阶段）：{self._gate_str(last_gate_ok)}\n"
            f"上一阶段产出片段：\n{last_output[:1200]}\n\n"
            f"请输出下一步决策（仅一个 ```decision 块）。"
        )
        text = self.llm.complete(
            system=self._base_prompt + "\n\n" + self._build_decision_instr(order), user=user)
        return self._parse_decision(text, order)

    @staticmethod
    def _parse_decision(text, order):
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
        if d["action"] != "done" and role not in order:
            return None
        return d

    # ---------------- 决策：Mock 状态机（等价于旧管线 + 回退） ----------------
    @staticmethod
    def _mock_decide(last_role, last_gate_ok, pos, order):
        if last_role is None:
            return "next", order[0]
        if last_role == "retrospector":
            return "done", None
        if last_role in GATE_ROLES and last_gate_ok is False:
            return "rollback", ROLLBACK_TARGET
        npos = (pos + 1) if pos >= 0 else 0
        return "next", order[npos]

    @staticmethod
    def _fallback(last_role, last_gate_ok, pos, order):
        if last_role in GATE_ROLES and last_gate_ok is False:
            return "rollback", ROLLBACK_TARGET
        if last_role == "retrospector":
            return "done", None
        npos = (pos + 1) if pos >= 0 else 0
        if npos < len(order):
            return "next", order[npos]
        return "done", None

    # ---------------- 主循环 ----------------
    def run(self, requirement: str, use_sandbox: bool = True, doc: bool = False) -> "Job":
        from .job import Job
        from .doclint_check import DocLint

        stages = self._build_stages(doc)
        order = [r for r, _ in stages]
        role_label = dict(stages)

        job = Job(requirement, with_sandbox=use_sandbox)
        job.note("Orchestrator(LLM-agent) 启动，需求：" + requirement)
        if doc:
            job.note("文档撰写阶段已启用：documenter 产出须通过 doclint 校验闸门")
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
        force_redo_role = None          # doclint 闸门触发：强制重做某角色
        doclint_retries = {}            # role -> 连续不通过次数

        while True:
            iters += 1
            if iters > MAX_ITER:
                job.fail(f"超过最大迭代次数({MAX_ITER})，任务未收敛")
                break

            # 1) 决策（doclint 强制重做优先覆盖）
            if force_redo_role is not None:
                action, role, redo = "next", force_redo_role, True
                force_redo_role = None
                job.note(f"文档校验未通过 → 强制重做：{role_label[role]}")
            elif isinstance(self.llm, MockLLM):
                action, role = self._mock_decide(last_role, last_gate_ok, pos, order)
                redo = False
            else:
                dec = self._decide(requirement, ctx, last_role, last_output,
                                   last_gate_ok, order, role_label)
                if dec is None:
                    job.note("决策解析失败，启用兜底逻辑")
                    action, role = self._fallback(last_role, last_gate_ok, pos, order)
                else:
                    action, role = dec["action"], dec.get("role")
                redo = False

            # 2) 安全网：门禁 FAIL 强制回退，覆盖模型决策（确保「活干好」）
            if last_role in GATE_ROLES and last_gate_ok is False:
                action, role = "rollback", ROLLBACK_TARGET
                redo = True
                job.note("门禁 FAIL，强制回退到开发重做（覆盖模型决策）")

            # 3) 质量闸门：done 前必须验证通过
            if action == "done":
                if not verify_passed:
                    job.note("请求 done 但验证尚未 PASS，强制重跑验证")
                    action, role = "next", "verifier"
                    redo = False
                else:
                    break  # 任务完成

            # 4) 非法角色兜底
            if role not in order:
                job.note(f"决策角色非法：{role}，启用兜底")
                action, role = self._fallback(last_role, last_gate_ok, pos, order)
                redo = False

            # 5) 执行该阶段 Pod
            label = role_label[role]
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

            # 6) 文档校验闸门（仅 DOCLINT_ROLES）
            if role in DOCLINT_ROLES:
                lint = DocLint().validate_text(output, filename=f"{role}.md")
                if not lint.ok:
                    doclint_retries[role] = doclint_retries.get(role, 0) + 1
                    n = doclint_retries[role]
                    ctx += f"\n（文档校验：FAIL - {lint.summary}）\n"
                    job.note(f"文档校验 FAIL：{lint.summary}（第 {n} 次）")
                    if n > DOCLINT_MAX_RETRY:
                        job.fail(f"{label} 文档校验连续 {DOCLINT_MAX_RETRY} 次不通过，任务失败")
                        break
                    # 退回重做，把反馈喂给 agent 改稿
                    ctx += f"\n## 文档校验反馈（请据此改稿后重交）\n{lint.feedback}\n"
                    force_redo_role = role
                    last_role = role
                    pos = order.index(role)
                    last_output = output
                    last_gate_ok = None
                    continue   # 下一轮强制重做该角色
                ctx += f"\n（文档校验：PASS - {lint.summary}）\n"
                job.note(f"文档校验 PASS（{lint.summary}）")
                doclint_retries[role] = 0

            # 7) 门禁判定，回填决策上下文
            if role in GATE_ROLES:
                last_gate_ok = self._gate(label, output)
                verdict = "PASS" if last_gate_ok else "FAIL"
                ctx += f"（门禁判定：{verdict}）\n"
                if role == "verifier" and last_gate_ok:
                    verify_passed = True
                job.note(f"{label} 门禁：{verdict}")
                if not last_gate_ok:
                    job.note(f"{label} 未通过，将回退到 {role_label[ROLLBACK_TARGET]} 重做")
            else:
                last_gate_ok = None

            last_role = role
            pos = order.index(role)
            last_output = output

        if job.state == "running":
            job.done()
            job.note("验证通过且复盘完成，任务『活干好』✓")

        job.save()
        return job
