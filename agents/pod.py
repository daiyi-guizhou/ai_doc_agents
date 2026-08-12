"""Agent Pod：无状态 worker，类 k8s Pod。

生命周期：Scheduler.spawn(role) 创建 → pod.run(task, context) 执行一次 →
Scheduler.destroy(pod) 销毁。自身不持久化任何状态，提示词在 spawn 时从文档加载。
"""
import uuid

from . import prompts


class Pod:
    def __init__(self, scheduler, role: str, llm):
        self.scheduler = scheduler
        self.role = role
        self.llm = llm
        self.spec = prompts.load_role(role)  # 提示词来自本地文档（SSOT）
        self.id = f"pod-{role}-{str(uuid.uuid4())[:8]}"

    def run(self, task: str, context: str = "") -> str:
        """执行一次任务，返回该角色产出。提示词 + 累积上下文拼成 system。"""
        system = self.spec["prompt"]
        if context:
            system += "\n\n# 任务上下文（前序阶段产出，逐步累积）\n" + context
        return self.llm.complete(system=system, user=task)

    def destroy(self):
        """销毁 Pod，从调度器活动表中移除（无状态，不保留任何信息）。"""
        self.scheduler._active.pop(self.id, None)
