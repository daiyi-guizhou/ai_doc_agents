"""Agent Pod：无状态 worker，类 k8s Pod。

生命周期：Scheduler.spawn(role) 创建 → pod.run(task, context) 执行一次 →
Scheduler.destroy(pod) 销毁。自身不持久化任何状态，提示词在 spawn 时从文档加载。

若 run 时传入 sandbox，则本 Pod 拥有「真实执行」能力：模型可在产出中声明
write_file / read_file / list_dir / run 动作（见 agents/tools.py 协议），Pod 在沙箱内
按序执行并把结果回填。developer / tester 借此真正读写文件、跑命令，而非只生成文本。
"""
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
        sandbox 为 Sandbox 实例 → 解析/执行工具动作，并附真实执行记录。
        """
        system = self.spec["prompt"]
        if sandbox is not None:
            system += "\n\n" + tools.TOOL_INSTRUCTIONS

        if context:
            system += "\n\n# 任务上下文（前序阶段产出，逐步累积）\n" + context

        output = self.llm.complete(system=system, user=task, role=self.role)

        if sandbox is None:
            return output

        # 决定动作：Mock 用确定性真实动作；真实 LLM 从产出中解析 actions 块
        if isinstance(self.llm, MockLLM):
            actions = tools.mock_actions(self.role, task, self.project_root)
        else:
            actions = tools.parse_actions(output)

        if not actions:
            return output

        results = tools.execute_actions(sandbox, actions)
        exec_record = tools.format_results(results)

        # 真实 LLM：把执行结果回填，请求一次收尾总结（含 通过/失败 结论）
        if isinstance(self.llm, MockLLM):
            return output.strip() + "\n\n" + exec_record

        final = self.llm.complete(
            system=system + "\n\n# 工具执行结果（沙箱内真实发生）\n" + exec_record,
            user="请基于上方真实执行结果，给出本阶段最终交付物小结，"
                 "并在开头明确给出 通过 / 失败（或 PASS/FAIL）结论。",
            role=self.role,
        )
        return final.strip() + "\n\n" + exec_record

    def destroy(self):
        """销毁 Pod，从调度器活动表中移除（无状态，不保留任何信息）。"""
        self.scheduler._active.pop(self.id, None)
