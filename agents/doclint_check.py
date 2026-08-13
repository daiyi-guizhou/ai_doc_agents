"""DocLint 校验器：把「写文档的 agent」的产出交给 tools/doclint.py 校验。

与 docs 治理共用同一套规则（frontmatter / type / status / 死链），
保证「agent 写出来的文档」和「人维护的文档」是同一把尺子。

设计要点：
- 校验在临时目录里对单篇文档进行（flat 放置，不走 adr/rfcs 序号连续性检查），
  文档内部的 [[wikilinks]] 若指向 vault 外笔记只产生 warning（不致命），
  因此闸门默认只看 error 级别；warning 仅作为反馈喂给 agent 改进。
- 通过 strict=True 可让 warning 也致命（一般仅提交前守门才需要）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOCLINT = os.path.join(_ROOT, "tools", "doclint.py")


def _unwrap_fence(text: str) -> str:
    """剥离开头可能出现的 ``` 代码块包裹（真实 LLM 常把整篇文档包进 ```markdown）。

    仅当文本以 ``` 起始、且末尾也有 ``` 时才剥离，取最外层之间的内容；
    不影响正常文档（人类维护的文档不会以代码块包裹整篇）。
    """
    s = text.lstrip("\ufeff").lstrip("\n")
    if not s.startswith("```"):
        return text
    nl = s.find("\n")
    if nl == -1:
        return text
    last = s.rfind("```")
    if last <= nl:
        return text
    return s[nl + 1:last].rstrip("\n") + "\n"


class DocLintResult:
    def __init__(self, ok, errors, warnings, raw):
        self.ok = ok
        self.errors = errors
        self.warnings = warnings
        self.raw = raw

    @property
    def summary(self):
        n = len(self.errors)
        if n == 0:
            return "通过" if not self.warnings else f"通过（{len(self.warnings)} 条警告）"
        return f"{n} 个错误，{len(self.warnings)} 条警告"

    @property
    def feedback(self):
        """给 agent 的改稿反馈（行内可读）。"""
        lines = []
        for e in self.errors:
            lines.append(f"- [error] {e.get('file', '')}: {e.get('message', '')}")
        for w in self.warnings:
            lines.append(f"- [warn]  {w.get('file', '')}: {w.get('message', '')}")
        return "\n".join(lines) if lines else "无问题"


class DocLint:
    """包装 tools/doclint.py，对一段 Markdown 文本做合规校验。"""

    def __init__(self, doclint_path=_DOCLINT, python=sys.executable, strict=False):
        self.doclint_path = doclint_path
        self.python = python
        self.strict = strict

    def validate_text(self, text, filename="doc.md"):
        """把 text 当作单篇文档校验，返回 DocLintResult。"""
        if not os.path.isfile(self.doclint_path):
            return DocLintResult(False, [], [f"doclint 不存在: {self.doclint_path}"], "")
        # 真实 LLM 可能把整篇文档包进 ``` 代码块，先剥离外层包裹再校验
        text = _unwrap_fence(text)
        d = tempfile.mkdtemp(prefix="doclint_")
        try:
            path = os.path.join(d, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            cmd = [self.python, self.doclint_path, d, "--json"]
            if self.strict:
                cmd.append("--strict")
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            except Exception as e:  # 执行异常不致命，避免卡死编排
                return DocLintResult(False, [], [f"doclint 执行异常: {e}"], "")
            out = proc.stdout or ""
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                return DocLintResult(False, [], [f"doclint 输出无法解析: {out[-400:]}"], out)
            issues = data.get("issues", [])
            errors = [i for i in issues if i.get("severity") == "error"]
            warnings = [i for i in issues if i.get("severity") == "warning"]
            ok = len(errors) == 0
            return DocLintResult(ok, errors, warnings, out)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def validate_path(self, path):
        """校验磁盘上某个真实文档（用于校验已落库的文档）。"""
        with open(path, encoding="utf-8") as f:
            return self.validate_text(f.read(), os.path.basename(path))

    def validate_dir(self, path):
        """校验磁盘上某个目录（递归 .md），用于治理复检被开发项目的 docs/。"""
        if not os.path.isdir(path):
            return DocLintResult(False, [], [f"目录不存在: {path}"], "")
        cmd = [self.python, self.doclint_path, path, "--json"]
        if self.strict:
            cmd.append("--strict")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as e:  # 执行异常不致命，避免卡死编排
            return DocLintResult(False, [], [f"doclint 执行异常: {e}"], "")
        out = proc.stdout or ""
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return DocLintResult(False, [], [f"doclint 输出无法解析: {out[-400:]}"], out)
        issues = data.get("issues", [])
        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [i for i in issues if i.get("severity") == "warning"]
        ok = len(errors) == 0
        return DocLintResult(ok, errors, warnings, out)
