"""工具协议：让 developer / tester 这类 Pod 能真正行动，而不只生成文本。

协议（系统的「手」）：模型在其产出中以一个 fenced 块声明要执行的动作，
Pod 解析后在沙箱内按序执行，并把结果回填给模型做收尾。格式：

    ```actions
    [
      {"action": "write_file", "path": "solution.py", "content": "..."},
      {"action": "run", "cmd": ["python", "solution.py"], "timeout": 30}
    ]
    ```

支持动作：write_file / read_file / edit_file / list_dir / run。
Mock 模式下，developer/tester 由 mock_actions() 给出确定性的真实动作（真的写文件、真的跑命令），
以此在零密钥环境下也能证明沙箱能力可用。
"""
import json
import os
import re

from .sandbox import Sandbox

ACTION_FENCE = re.compile(r"```actions\s*(.*?)```", re.DOTALL | re.IGNORECASE)

TOOL_INSTRUCTIONS = """\
# 你拥有沙箱执行工具（真实读写文件、跑命令）

当本阶段需要产出可运行代码或执行测试时，请在回复中包含如下 fenced 块，
系统会在沙箱内按序执行，并把结果回填给你做收尾总结：

```actions
[
  {"action": "read_file", "path": "src/app.py"},
  {"action": "edit_file", "path": "src/app.py",
   "old": "    return 0", "new": "    return 3  # 改为查库结果", "occurrence": "first"},
  {"action": "run", "cmd": ["python", "tests/run_tests.py"], "timeout": 30}
]
```

动作清单：
- read_file:  {"path": "..."}                                  读出现有文件内容（改之前务必先读）
- write_file: {"path": "相对沙箱的路径", "content": "文件全文"}   整文件覆写（适合新建文件）
- edit_file:  {"path": "...", "old": "待替换片段", "new": "新片段",
               "occurrence": "first"|"all"}                    定点替换（适合改已有文件，安全、不易丢内容）
- list_dir:   {"path": "."}
- run:        {"cmd": ["可执行文件(白名单)", "参数..."], "timeout": 30}

约束：路径相对于沙箱根，禁止越界；命令仅限白名单（python/node/pytest/git 等）。
优先用 edit_file 改既有文件（先 read_file 再 edit_file），避免整文件覆写丢失内容。"""


# OpenAI 标准 tool-calling 协议所用的工具 schema（真实 LLM 走此结构化通道，
# 不再依赖模型吐自定义 ```actions fence 文本——后者各模型格式不一、易解析失败）。
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取沙箱内现有文件内容（改之前务必先读）。path 相对沙箱根。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string",
                                        "description": "相对沙箱根的文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "整文件覆写（适合新建文件）。path 相对沙箱根，content 为文件全文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "文件全文"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": ("定点替换文件中某段文本（适合改既有文件，安全、不易丢内容）。"
                            "old 须与文件内容精确一致；new 为替换后内容；"
                            "occurrence 为 first（替换首个匹配）或 all（全部）。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string", "description": "待替换的精确片段"},
                    "new": {"type": "string", "description": "替换后的新片段"},
                    "occurrence": {"type": "string", "enum": ["first", "all"],
                                   "description": "替换第一个匹配还是全部，默认 first"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出沙箱内某目录的文件（path 相对沙箱根，默认 '.'）。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run",
            "description": ("在沙箱内执行一条命令（白名单：python/node/pytest/git 等）。"
                            "cmd 为命令及参数列表，timeout 为超时秒数。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "array", "items": {"type": "string"},
                            "description": "命令及参数，如 [\"python\",\"tests/run_tests.py\"]"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
                },
                "required": ["cmd"],
            },
        },
    },
]


def parse_actions(text: str):
    """从模型产出中提取动作列表；无则返 []。"""
    m = ACTION_FENCE.search(text)
    if not m:
        return []
    try:
        data = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def execute_actions(sandbox: Sandbox, actions: list) -> list:
    """在沙箱内执行动作，返回结果列表（每项含 action/ok/detail）。"""
    results = []
    for i, act in enumerate(actions):
        if not isinstance(act, dict):
            results.append({"action": "?", "ok": False, "detail": "动作格式错误"})
            continue
        kind = act.get("action")
        try:
            if kind == "write_file":
                detail = sandbox.write_file(act["path"], act.get("content", ""))
                results.append({"action": "write_file", "path": act["path"], "ok": True, "detail": detail})
            elif kind == "edit_file":
                detail = sandbox.edit_file(act["path"], act.get("old", ""),
                                           act.get("new", ""), act.get("occurrence", "first"))
                results.append({"action": "edit_file", "path": act["path"], "ok": True, "detail": detail})
            elif kind == "read_file":
                detail = sandbox.read_file(act["path"])
                results.append({"action": "read_file", "path": act["path"], "ok": True, "detail": detail})
            elif kind == "list_dir":
                detail = sandbox.list_dir(act.get("path", "."))
                results.append({"action": "list_dir", "path": act.get("path", "."), "ok": True, "detail": detail})
            elif kind == "run":
                res = sandbox.run(act.get("cmd", []), int(act.get("timeout", 60)))
                results.append({"action": "run", "cmd": act.get("cmd"), "ok": res["rc"] == 0, "detail": res})
            else:
                results.append({"action": kind, "ok": False, "detail": f"未知动作: {kind}"})
        except Exception as e:  # 沙箱边界/IO 异常都转为结构化结果，不中断编排
            results.append({"action": kind, "ok": False, "detail": f"{type(e).__name__}: {e}"})
    return results


def format_results(results: list) -> str:
    lines = ["## 沙箱执行记录", ""]
    for i, r in enumerate(results):
        status = "OK " if r["ok"] else "ERR"
        head = f"- [{status}] {i+1}. {r['action']}"
        if "path" in r:
            head += f" → {r['path']}"
        if "cmd" in r:
            head += f" → {' '.join(r['cmd'])}"
        lines.append(head)
        d = r["detail"]
        if isinstance(d, dict):  # run 的结果
            lines.append(f"    rc={d.get('rc')}")
            if d.get("stdout"):
                lines.append("    stdout:")
                lines.append(_indent(d["stdout"]))
            if d.get("stderr"):
                lines.append("    stderr:")
                lines.append(_indent(d["stderr"]))
        else:
            lines.append(_indent(str(d)))
    return "\n".join(lines)


def _indent(s: str, n: int = 4) -> str:
    return "\n".join((" " * n) + ln for ln in s.splitlines())


def mock_actions(role: str, requirement: str, project_root: "str | None" = None) -> list:
    """Mock 模式下 developer/tester 的确定性真实动作（沙箱内真写真跑）。

    project_root 提供时，tester 改为运行「后端项目自身的测试入口」
    （tests/run_tests.py 或 pytest），以验证「在真实项目里跑测试」。
    """
    req_line = requirement.strip().replace("\n", " ")
    if role == "developer":
        # 绑定了后端项目：真实读现有源、定点 edit、并在项目内跑测试（演示可回滚的改代码）
        if project_root:
            old = (
                'def user_count() -> int:\n'
                '    """（占位）返回当前用户数；真实实现应查库。"""\n'
                '    return 0'
            )
            new = old + (
                '\n\n'
                'def add_user(name: str) -> str:\n'
                '    """mock 新增：注册用户。"""\n'
                '    return f"user {name} added"\n'
            )
            return [
                {"action": "read_file", "path": "src/app.py"},
                {"action": "edit_file", "path": "src/app.py", "old": old, "new": new,
                 "occurrence": "first"},
                {"action": "run", "cmd": ["python", "tests/run_tests.py"], "timeout": 30},
            ]
        code = (
            f"# Auto-generated by developer pod (MOCK)\n"
            f"# Requirement: {req_line}\n"
            f"def run():\n"
            f"    return \"implemented: {req_line[:60]}\"\n\n"
            f"if __name__ == \"__main__\":\n"
            f"    print(\"run() ->\", run())\n"
        )
        return [
            {"action": "write_file", "path": "solution.py", "content": code},
            {"action": "run", "cmd": ["python", "solution.py"], "timeout": 30},
        ]
    if role == "tester":
        if project_root:
            test_cmd = _detect_project_test(project_root)
            if test_cmd:
                return [{"action": "run", "cmd": test_cmd, "timeout": 60}]
        test = (
            "import solution\n"
            "assert solution.run(), 'run() 不应为空'\n"
            "print('TEST PASS')\n"
        )
        return [
            {"action": "write_file", "path": "_test_solution.py", "content": test},
            {"action": "run", "cmd": ["python", "_test_solution.py"], "timeout": 30},
        ]
    return []


def _detect_project_test(project_root: str):
    """返回后端项目可执行的测试命令（列表）；无则 None。"""
    run_tests = os.path.join(project_root, "tests", "run_tests.py")
    if os.path.isfile(run_tests):
        return ["python", "tests/run_tests.py"]
    if os.path.isfile(os.path.join(project_root, "pytest.ini")) or \
       os.path.isfile(os.path.join(project_root, "pyproject.toml")):
        return ["pytest"]
    return None
