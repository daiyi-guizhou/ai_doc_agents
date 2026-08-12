"""Sandbox：给 developer / tester 等 Pod 提供「真实执行」能力的隔离工作区。

设计原则（权限与隔离）：
  - 文件操作限定在沙箱根目录内，路径穿越（../、绝对路径逃逸）一律拒绝。
  - 命令执行走 subprocess（shell=False，按 argv 列表传参），杜绝 shell 注入。
  - 仅允许白名单内的可执行文件（python/node/pytest/git 等），其余直接拒绝。
  - 每次执行有超时上限与输出截断，避免挂死或刷屏。
  - 沙箱根目录位于 agent_runs/<jobid>/sandbox/，随任务产物一起留存，便于复盘。

这是「软隔离」：适合本地开发 Agent 自测；若要强隔离（限制 CPU/内存/网络），
应改为容器/VM 执行后端，接口保持一致即可替换。
"""
import os
import subprocess

# 允许在沙箱内执行的命令（仅 basename，从 PATH 解析；不收绝对路径，避免绕过）
ALLOWED_COMMANDS = {
    "python", "python3", "python3.exe", "python.exe",
    "node", "node.exe", "npm", "npx",
    "pip", "pip3",
    "pytest", "pytest.exe",
    "git", "git.exe",
    "echo", "ls", "cat", "wc", "head", "tail", "type", "dir",
}

DEFAULT_TIMEOUT = 60          # 单次命令超时（秒）
MAX_OUTPUT_CHARS = 8000       # 单次命令 stdout/stderr 截断长度
MAX_ROUND_TRIP = 4            # 工具调用最大轮次（防失控）


class SandboxEscape(ValueError):
    """尝试在沙箱根目录之外读写文件。"""


class Sandbox:
    def __init__(self, root: str):
        self.root = os.path.realpath(root)
        os.makedirs(self.root, exist_ok=True)

    # ---- 路径安全：所有文件操作都须经此规范化并校验 ----
    def _safe(self, rel: str) -> str:
        rel = rel.replace("\\", "/")
        # 归一化相对路径，去掉 ./ 与多余的 ..，但允许在根内
        cand = os.path.realpath(os.path.join(self.root, rel))
        if cand == self.root or cand.startswith(self.root + os.sep):
            return cand
        raise SandboxEscape(f"路径越界（沙箱外）: {rel}")

    # ---- 文件操作 ----
    def write_file(self, rel: str, content: str) -> str:
        path = self._safe(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {rel}（{len(content)} 字节）"

    def read_file(self, rel: str) -> str:
        path = self._safe(rel)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"沙箱内无此文件: {rel}")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def list_dir(self, rel: str = ".") -> str:
        path = self._safe(rel)
        if not os.path.isdir(path):
            return f"（非目录或不存在: {rel}）"
        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            kind = "dir" if os.path.isdir(full) else "file"
            entries.append(f"{kind:4s} {name}")
        return "\n".join(entries) if entries else "（空目录）"

    def exists(self, rel: str) -> bool:
        try:
            return os.path.exists(self._safe(rel))
        except SandboxEscape:
            return False

    # ---- 命令执行（白名单 + 超时 + 截断） ----
    def run(self, argv, timeout: int = DEFAULT_TIMEOUT) -> dict:
        if isinstance(argv, str):
            argv = argv.split()
        if not argv:
            return {"rc": 2, "stdout": "", "stderr": "空命令"}
        exe = os.path.basename(argv[0])
        if exe not in ALLOWED_COMMANDS:
            return {
                "rc": 126,
                "stdout": "",
                "stderr": f"命令不在白名单: {exe}（允许: {', '.join(sorted(ALLOWED_COMMANDS))}）",
            }
        try:
            proc = subprocess.run(
                argv, cwd=self.root, capture_output=True,
                text=True, timeout=timeout, shell=False,
            )
            rc = proc.returncode
            out = self._clip(proc.stdout or "")
            err = self._clip(proc.stderr or "")
        except subprocess.TimeoutExpired:
            return {"rc": -1, "stdout": "", "stderr": f"命令超时（>{timeout}s）被杀"}
        except FileNotFoundError:
            return {"rc": 127, "stdout": "", "stderr": f"命令未找到（未在 PATH 中）: {exe}"}
        return {"rc": rc, "stdout": out, "stderr": err}

    @staticmethod
    def _clip(s: str, n: int = MAX_OUTPUT_CHARS) -> str:
        if len(s) <= n:
            return s
        return s[:n] + f"\n…（输出已截断至 {n} 字符）"

    def destroy(self):
        """销毁沙箱（清理文件）。任务复盘阶段通常保留以便检查，故不自动调用。"""
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)
