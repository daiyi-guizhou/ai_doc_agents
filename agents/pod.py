"""Agent Pod：无状态 worker，类 k8s Pod。

生命周期：Scheduler.spawn(role) 创建 → pod.run(task, context) 执行一次 →
Scheduler.destroy(pod) 销毁。自身不持久化任何状态，提示词在 spawn 时从文档加载。

若 run 时传入 sandbox，则本 Pod 拥有「真实执行」能力：模型可在产出中声明
write_file / read_file / list_dir / run 动作（见 agents/tools.py 协议），Pod 在沙箱内
按序执行并把结果回填。developer / tester 借此真正读写文件、跑命令，而非只生成文本。
"""
import json
import uuid

from . import prompts
from .llm import MockLLM
from . import tools


class Pod:
    def __init__(self, scheduler, role: str, llm, project_root=None):
        self.scheduler = scheduler
        self.role = role
        self.llm = llm
        self.project_root = project_root
        self.spec = prompts.load_role(role)  # 提示词来自本地文档（SSOT）
        self.id = f"pod-{role}-{str(uuid.uuid4())[:8]}"

    def run(self, task: str, context: str = "", sandbox=None) -> str:
        """执行一次任务，返回该角色产出。

        sandbox 为 None → 纯文本生成（原行为）。
        sandbox 为 Sandbox 实例 → 真实执行工具动作并附执行记录：
          - Mock LLM：用确定性真实动作（mock_actions），解析 ```actions fence。
          - 真实 LLM：走 OpenAI 标准 tool-calling 协议（tools.TOOL_SCHEMAS），
            多轮执行并把结果回填，模型可靠产出结构化调用而非自定义文本。
        """
        system = self.spec["prompt"]
        if sandbox is not None:
            if isinstance(self.llm, MockLLM):
                system += "\n\n" + tools.TOOL_INSTRUCTIONS
            else:
                system += (
                    "\n\n# 你拥有沙箱执行工具（read_file / write_file / edit_file / "
                    "list_dir / run），需要读写文件或跑命令时直接调用对应工具；"
                    "系统会在沙箱内真实执行并把结果回填给你做收尾。"
                )

        if context:
            system += "\n\n# 任务上下文（前序阶段产出，逐步累积）\n" + context

        if sandbox is None:
            return self.llm.complete(system=system, user=task, role=self.role)

        # ---- 沙箱路径 ----
        if isinstance(self.llm, MockLLM):
            actions = tools.mock_actions(self.role, task, self.project_root)
            if not actions:
                return self.llm.complete(system=system, user=task, role=self.role)
            results = tools.execute_actions(sandbox, actions)
            exec_record = tools.format_results(results)
            out = self.llm.complete(system=system, user=task, role=self.role)
            return out.strip() + "\n\n" + exec_record

        # ---- 真实 LLM + 沙箱：tool-calling 多轮执行 ----
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
        exec_record = ""
        MAX_TOOL_ROUNDS = 5
        out = ""
        for _ in range(MAX_TOOL_ROUNDS):
            msg = self.llm.chat(messages, tools=tools.TOOL_SCHEMAS)
            messages.append(msg)
            tcs = msg.get("tool_calls") or []
            if not tcs:
                out = msg.get("content") or ""
                break
            actions = []
            for tc in tcs:
                fn = tc.get("function", {})
                name = fn.get("name")
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except Exception:
                        args = {}
                elif not isinstance(args, dict):
                    args = {}
                actions.append({"action": name, **args})
            results = tools.execute_actions(sandbox, actions)
            exec_record = tools.format_results(results)
            for tc, r in zip(tcs, results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": json.dumps(r, ensure_ascii=False),
                })
        else:
            out = messages[-1].get("content") or ""

        if exec_record:
            final = self.llm.complete(
                system=system + "\n\n# 工具执行结果（沙箱内真实发生）\n" + exec_record,
                user="请基于上方真实执行结果，给出本阶段最终交付物小结，"
                     "并在开头明确给出 通过 / 失败（或 PASS/FAIL）结论。",
                role=self.role,
            )
            return final.strip() + "\n\n" + exec_record
        return out

    def destroy(self):
        """销毁 Pod，从调度器活动表中移除（无状态，不保留任何信息）。"""
        self.scheduler._active.pop(self.id, None)
