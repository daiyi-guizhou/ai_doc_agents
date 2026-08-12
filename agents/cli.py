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

    run_p = sub.add_parser("run", help="发起一次任务（先对话澄清需求，再 7 阶段 → 复盘）")
    run_p.add_argument("requirement", nargs="?", default=None,
                       help="用自然语言描述的需求（省略则进入对话澄清，多轮确认后再开工）")
    run_p.add_argument("--mock", action="store_true", help="强制使用 Mock LLM（离线）")
    run_p.add_argument("--doc", action="store_true",
                       help="启用文档撰写阶段（documenter 产出须过 doclint 校验）")
    run_p.add_argument("--max-iter", type=int, default=12, help="最大阶段迭代次数")
    run_p.add_argument("--no-sandbox", action="store_true",
                       help="关闭沙箱（developer/tester 退回纯文本生成）")
    run_p.add_argument("--yes", "-y", action="store_true",
                       help="跳过对话澄清，直接按给定需求开工（需配合需求文本）")
    run_p.add_argument("--script", metavar="FILE", default=None,
                       help="从文件逐行读取对话输入（每行一条用户发言），用于自动化/测试")

    sub.add_parser("roles", help="列出可用角色（来自 docs/agents）")

    web_p = sub.add_parser("web", help="启动网页版对话澄清（多对话、开始工作）")
    web_p.add_argument("--port", type=int, default=8000, help="监听端口")
    web_p.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    web_p.add_argument("--mock", action="store_true", help="强制使用 Mock LLM（离线）")
    web_p.add_argument("--doc", action="store_true",
                       help="默认启用文档撰写阶段（documenter 产出须过 doclint 校验）")
    web_p.add_argument("--no-sandbox", action="store_true",
                       help="关闭沙箱（developer/tester 退回纯文本生成）")
    return p


def _clarify(llm, initial, script_lines, use_sandbox, doc, mode):
    """进入多轮需求对话澄清；用户确认后返回『需求确认单』作为正式需求。"""
    from .conversation import Clarifier

    c = Clarifier(llm, initial=initial)
    print(f"[agents] 模式={mode}  沙箱={'开' if use_sandbox else '关'}  "
          f"文档阶段={'开' if doc else '关'}  （需求对话澄清中，回复『确认』开工）\n")

    def say(msg):
        print("助手> " + msg + "\n")

    def take():
        if script_lines is not None:
            return script_lines.pop(0) if script_lines else "确认"
        try:
            return input("你> ").strip()
        except EOFError:
            return "确认"

    say(c.start())
    while not c.done:
        u = take()
        if not u:
            continue
        c.submit(u)
        if c.done:
            break
        say(c.pending)

    spec = c.spec or c.requirement
    print("=" * 56)
    print("需求已确认，开始执行：\n")
    print(spec)
    print("=" * 56 + "\n")
    return spec


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

    if args.cmd == "web":
        from . import web
        web.run(host=args.host, port=args.port, mock=args.mock,
                doc=args.doc, no_sandbox=args.no_sandbox)
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

    # ---- 需求获取：直接模式 or 对话澄清 ----
    if args.yes:
        if not args.requirement:
            print("[agents] 错误：--yes 模式需要直接提供需求文本（或去掉 --yes 进入对话）。",
                  file=sys.stderr)
            return 2
        requirement = args.requirement
        print(f"[agents] 模式={mode}  沙箱={'开' if use_sandbox else '关'}  "
              f"文档阶段={'开' if args.doc else '关'}  （对话澄清已跳过）")
    else:
        script_lines = None
        if args.script:
            with open(args.script, encoding="utf-8") as fh:
                script_lines = [ln.strip() for ln in fh if ln.strip()]
        requirement = _clarify(llm, args.requirement, script_lines,
                               use_sandbox, args.doc, mode)

    job = orch.run(requirement, use_sandbox=use_sandbox, doc=args.doc,
                   max_iter=args.max_iter)

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
