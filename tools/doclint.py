#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doclint - 项目文档治理校验工具。

校验 docs/ 下 Markdown 文档的 frontmatter、命名规则、生命周期与内部死链。
同时支持 Obsidian 的 [[wikilinks]] 死链检测（解析为 vault 内笔记名）。
无第三方依赖，使用托管 Python 直接运行：

    python tools/doclint.py docs
    python tools/doclint.py docs --strict      # warning 也视为失败
    python tools/doclint.py docs --today 2027-01-01   # 覆盖今天（测试用）
    python tools/doclint.py docs --json         # JSON 输出（供 inspect 聚合）
"""
import argparse
import os
import re
import sys
from datetime import date, datetime

REQUIRED_FIELDS = ["title", "type", "owner", "status", "updated"]
VALID_TYPES = {"adr", "rfc", "design", "api", "runbook", "guide", "spec", "meeting", "index"}
VALID_STATUS = {"draft", "review", "stale", "active", "deprecated"}
EXEMPT_NAMES = {"README.md", "_template.md"}

LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")
SEQ_RE = re.compile(r"^(\d{4})-.*\.md$")
MEETING_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.*\.md$")


def parse_frontmatter(text):
    """返回 (data_dict, body_text)。无合法 frontmatter 时 (None, text)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, text
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])
    data = {}
    for line in fm_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            val = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()] if inner else []
        else:
            val = val.strip("\"'")
        data[key] = val
    return data, body


def parse_cycle(value, default=90):
    if not value:
        return default
    m = re.match(r"^(\d+)\s*([dmy]?)$", str(value).strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    return {"d": n, "m": n * 30, "y": n * 365}[m.group(2) or "d"]


def parse_date(value):
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def check_file(path, root, today, stems=None):
    issues = []
    name = os.path.basename(path)
    rel = os.path.relpath(path, root).replace("\\", "/")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    if name in EXEMPT_NAMES:
        return issues  # 目录索引与模板豁免 frontmatter 校验

    data, _body = parse_frontmatter(text)
    if data is None:
        issues.append(("error", rel, "缺少 YAML frontmatter（--- 包裹的元数据块）"))
        return issues

    for field in REQUIRED_FIELDS:
        v = data.get(field)
        if v in (None, "", []):
            issues.append(("error", rel, "frontmatter 缺少必填字段: " + field))

    ftype = data.get("type")
    if ftype and ftype not in VALID_TYPES:
        issues.append(("error", rel, "type 非法: '%s'，应为 %s" % (ftype, sorted(VALID_TYPES))))

    status = data.get("status")
    if status and status not in VALID_STATUS:
        issues.append(("error", rel, "status 非法: '%s'，应为 %s" % (status, sorted(VALID_STATUS))))

    updated = parse_date(data.get("updated")) if data.get("updated") else None
    if data.get("updated") is not None and updated is None:
        issues.append(("error", rel, "updated 不是合法日期(YYYY-MM-DD): " + str(data.get("updated"))))

    cycle = parse_cycle(data.get("review_cycle"))
    if data.get("review_cycle") is not None and cycle is None:
        issues.append(("warning", rel, "review_cycle 无法解析: " + str(data.get("review_cycle"))))

    if status == "active" and updated and cycle:
        age = (today - updated).days
        if age > cycle:
            issues.append(("warning", rel,
                           "已超 review_cycle(%dd)，过期 %d 天，建议复核或标 stale" % (cycle, age)))

    rel_dir = os.path.dirname(rel)
    if rel_dir in ("adr", "rfcs"):
        if not SEQ_RE.match(name):
            issues.append(("error", rel, rel_dir + "/ 下文件必须形如 NNNN-slug.md（4 位序号）"))
    elif rel_dir == "meetings":
        if not MEETING_RE.match(name):
            issues.append(("error", rel, "meetings/ 下文件必须形如 YYYY-MM-DD-slug.md"))

    # 内部 Markdown 死链检测
    base = os.path.dirname(path)
    for m in LINK_RE.finditer(text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = target.split("#")[0]
        if not target:
            continue
        resolved = os.path.normpath(os.path.join(base, target))
        ok = (os.path.isfile(resolved)
              or os.path.isfile(resolved + ".md")
              or (os.path.isdir(resolved) and os.path.isfile(os.path.join(resolved, "README.md"))))
        if not ok:
            issues.append(("error", rel, "内部死链: " + target))

    # Obsidian [[wikilinks]] 死链检测（解析为 vault 内笔记名）
    if stems:
        for wm in WIKI_RE.finditer(text):
            raw = wm.group(1).strip()
            if not raw or raw.lower().startswith(("http", "mailto:")):
                continue
            target = raw.split("|", 1)[0].split("#", 1)[0].strip().lower()
            if not target:
                continue
            if target not in stems:
                issues.append(("warning", rel, "wikilink 无法解析（无对应笔记）: [[" + raw + "]]"))
    return issues


def check_sequences(root):
    issues = []
    for d in ("adr", "rfcs"):
        folder = os.path.join(root, d)
        if not os.path.isdir(folder):
            continue
        nums = []
        for fn in os.listdir(folder):
            if fn in EXEMPT_NAMES:
                continue
            m = SEQ_RE.match(fn)
            if m:
                nums.append(int(m.group(1)))
        if not nums:
            continue
        nums.sort()
        expected = list(range(1, len(nums) + 1))
        if nums != expected:
            missing = ["%04d" % i for i in expected if i not in nums]
            issues.append(("error", d + "/", "序号不连续，缺失: " + ", ".join(missing)))
    return issues


def main():
    ap = argparse.ArgumentParser(description="项目文档治理校验")
    ap.add_argument("root", nargs="?", default="docs", help="文档根目录（默认 docs）")
    ap.add_argument("--strict", action="store_true", help="warning 也视为失败")
    ap.add_argument("--today", default=None, help="覆盖今天日期 YYYY-MM-DD（测试用）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（供 inspect 聚合）")
    args = ap.parse_args()

    today = parse_date(args.today) if args.today else date.today()
    root = args.root
    if not os.path.isdir(root):
        print("目录不存在: " + root)
        return 2

    # 收集所有笔记名（含相对路径与 basename），用于 wikilink 解析
    stems = set()
    for dirpath, _d, filenames in os.walk(root):
        _d[:] = [d for d in _d if not d.startswith(".")]  # 跳过 .reports / .git 等
        for fn in filenames:
            if fn.lower().endswith(".md"):
                relp = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
                stems.add(relp[:-3].lower())
                stems.add(os.path.basename(relp)[:-3].lower())

    all_issues = []
    for dirpath, _dirs, filenames in os.walk(root):
        _dirs[:] = [d for d in _dirs if not d.startswith(".")]  # 跳过 .reports / .git 等
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                all_issues += check_file(os.path.join(dirpath, fn), root, today, stems)
    all_issues += check_sequences(root)

    errors = [i for i in all_issues if i[0] == "error"]
    warnings = [i for i in all_issues if i[0] == "warning"]

    if not args.json:
        for sev, rel, msg in all_issues:
            tag = "ERR " if sev == "error" else "WARN"
            print("  [%s] %s: %s" % (tag, rel, msg))
        print("-" * 60)
        print("扫描完成：error=%d  warning=%d" % (len(errors), len(warnings)))
        if not all_issues:
            print("OK 文档秩序良好，无问题。")

    failed = bool(errors) or (args.strict and bool(warnings))

    if args.json:
        import json as _json
        out = [{"severity": s, "file": r, "message": m} for s, r, m in all_issues]
        print(_json.dumps({"errors": len(errors), "warnings": len(warnings),
                           "issues": out}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
