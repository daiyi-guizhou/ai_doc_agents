"""Orchestrator 总控：编排 7 阶段流水线，决定何时『活干好』。

阶段（role, 中文标签）：
  0 需求分析  requirement-analyst
  1 概要设计  system-designer
  2 开发      developer
  3 测试      tester          (门禁：FAIL→回退到 开发)
  4 部署      deployer        (门禁：FAIL→回退到 开发)
  5 验证      verifier        (门禁：FAIL→回退到 开发)
  6 复盘      retrospector    (终态，通过后任务完成)

回退机制：门禁阶段产出 FAIL 时，回退到上游重做，直到验证通过且复盘完成。
全局迭代上限防止死循环；验证通过且复盘完成即判定『活干好』。
"""
from . import prompts

STAGES = [
    ("requirement-analyst", "需求分析"),
    ("system-designer", "概要设计"),
    ("developer", "开发"),
    ("tester", "测试"),
    ("deployer", "部署"),
    ("verifier", "验证"),
    ("retrospector", "复盘"),
]

# 门禁阶段失败时回退到的阶段下标
ROLLBACK = {3: 2, 4: 2, 5: 2}

MAX_ITER = 12


class Orchestrator:
    def __init__(self, scheduler):
        self.scheduler = scheduler

    def _task_for(self, label: str, role: str, requirement: str) -> str:
        return (
            f"你是本次任务的【{label}】阶段负责人（角色：{role}）。\n"
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
        # 测试/部署：显式失败标记才回退
        if head.startswith("FAIL") or "【失败】" in output or "失败：" in output[:40]:
            return False
        return True

    def run(self, requirement: str) -> "Job":
        from .job import Job
        job = Job(requirement)
        job.note("Orchestrator 启动，需求：" + requirement)
        ctx = f"原始需求：{requirement}\n"
        idx = 0
        iters = 0

        while idx < len(STAGES):
            iters += 1
            if iters > MAX_ITER:
                job.fail(f"超过最大迭代次数({MAX_ITER})，任务未收敛")
                break

            role, label = STAGES[idx]
            pod = self.scheduler.spawn(role)
            try:
                output = pod.run(task=self._task_for(label, role, requirement), context=ctx)
            finally:
                self.scheduler.destroy(pod)

            job.record(idx, label, role, output)
            ctx += f"\n## {label}（{role}）产出\n{output}\n"
            job.note(f"阶段完成：{label}（{role}）")

            if self._gate(label, output):
                idx += 1
            else:
                target = ROLLBACK.get(idx)
                if target is None:
                    job.fail(f"{label} 阶段失败且无回退路径")
                    break
                job.note(f"{label} 未通过，回退到 {STAGES[target][1]} 重做")
                idx = target

        if job.state == "running":
            job.done()
            job.note("验证通过且复盘完成，任务『活干好』✓")

        job.save()
        return job
