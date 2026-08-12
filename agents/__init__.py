"""ai_doc_agents · 多 Agent 框架（类 k8s Pod 架构）。

无状态 Agent Pod 由本地文档(docs/agents)提供系统提示词，
由 Scheduler 拉起/销毁，Orchestrator 总控编排 7 阶段流水线。

仅依赖 Python 标准库，使用托管 Python 直接运行：
    python -m agents run "做一个命令行待办工具"
    python -m agents run --mock "..."
    python -m agents roles
"""

__version__ = "0.1.0"
