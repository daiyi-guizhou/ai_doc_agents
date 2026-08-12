"""Pod 调度器：管理 Agent Pod 的无状态生命周期与并发。

类比 k8s 的 kubelet/controller：负责按 role 拉起 Pod、追踪活动实例、按需销毁。
调度器本身不持有业务状态，所有上下文由 Orchestrator 经 Job 流转。
"""
from .pod import Pod


class Scheduler:
    def __init__(self, llm, max_concurrent: int = 4, project_root=None):
        self.llm = llm
        self.max_concurrent = max_concurrent
        self.project_root = project_root
        self._active = {}  # pod_id -> Pod

    def spawn(self, role: str) -> Pod:
        """按 role 从文档加载提示词，拉起一个无状态 Pod。"""
        if len(self._active) >= self.max_concurrent:
            raise RuntimeError("已达最大并发 Pod 数，请稍后或调大 max_concurrent")
        pod = Pod(self, role, self.llm, project_root=self.project_root)
        self._active[pod.id] = pod
        return pod

    def destroy(self, pod: Pod):
        """销毁指定 Pod。"""
        pod.destroy()

    def active_count(self) -> int:
        return len(self._active)

    def active_roles(self):
        return [p.role for p in self._active.values()]
