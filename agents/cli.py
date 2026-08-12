"""CLI 入口：python -m agents run|roles。

示例：
    python -m agents run "做一个命令行待办工具"
    python -m agents run --mock "做一个命令行待办工具"
    python -m agents roles
"""
import argparse
import sys

from .config import load_dotenv, get_llm, is_mock
from . import prompts
from .scheduler import Scheduler
from .orchestrator import Orchestrator


def _build_parser():
    p = argparse.ArgumentParser(prog="agents", description="多 Agent Pod 框架 CLI")
    sub = p.add_subparsers(dest="cmd")

    run_p = sub.add_parser("run", help="发起一次任务（需求 → 7 阶段 → 复盘）")
    run_p.add_argument("requirement", help="用自然语言描述的需求")
    run_p.add_argument("--mock", action="store_true", help="强制使用 Mock LLM（离线）")
    run_p.add_argument("--doc", action="store_true",
                       help="启用文档撰写阶段（documenter 产出须过 doclint 校验）")
    run_p.add_argument("--max-iter", type=int, default=12, help="最大阶段迭代次数")
    run_p.add_argument("--no-sandbox", action="store_true",
                       help="关闭沙箱（developer/tester 退回纯文本生成）")

    sub.add_parser("roles", help="列出可用角色（来自 docs/agents）")
    return p


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    load_dotenv()

    if args.cmd == "roles":
        roles = prompts.list_roles()
        if not roles:
            print("未找到任何角色文档（docs/agents/*.md）。")
            return 1
        print(f"可用角色（{len(roles)}）：")
        for r in roles:
            spec = prompts.load_role(r)
            print(f"  - {r:22s} {spec['title']}")
        return 0

    if args.cmd != "run":
        parser.print_help()
        return 1

    if args.mock:
        import os
        os.environ["AGENTS_MOCK"] = "1"

    llm = get_llm()
    mode = "MOCK(离线)" if is_mock() else f"LLM({os.environ.get('OPENAI_MODEL','?')})"
    scheduler = Scheduler(llm)
    orch = Orchestrator(scheduler)

    use_sandbox = not args.no_sandbox
    print(f"[agents] 模式={mode}  沙箱={'开' if use_sandbox else '关'}  "
          f"文档阶段={'开' if args.doc else '关'}  需求={args.requirement}")
    job = orch.run(args.requirement, use_sandbox=use_sandbox, doc=args.doc)

    print("\n" + "=" * 56)
    print(f"Job {job.job_id}  状态={job.state}")
    print(f"需求：{job.requirement}")
    print("-" * 56)
    for s in job.stages:
        print(f"  {s['idx']:02d}. {s['label']:6s} <- {s['role']}")
    if job.error:
        print(f"错误：{job.error}")
    print("-" * 56)
    print(f"产物目录：{job.dir}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
