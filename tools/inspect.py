#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inspect - 文档库巡检：汇总 doclint 校验 + 语义去重 + 孤儿文档，产出报告。

运行 doclint.py 与 dedup.py，并额外检测"孤儿文档"（无任何入链的内容文档），
生成 docs/.reports/inspection-YYYYMMDD.md 供 AI / owner 复盘。

用法：
  python tools/inspect.py docs
  python tools/inspect.py docs --backend st
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC_PATH = os.path.join(ROOT, "tools", "doclint.py")
DEDUP_PATH = os.path.join(ROOT, "tools", "dedup.py")
EXEMPT = {"readme.md", "_template.md"}
WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def run(cmd):
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr
    except Exception as e:  # noqa
        return 255, str(e)


def collect_stems(root):
    stems = {}
    for dp, _d, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".md") and fn.lower() not in EXEMPT:
                rel = os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/")
                stems[rel[:-3].lower()] = rel
    return stems


def find_orphans(root):
    stems = collect_stems(root)
    inbound = set()
    for rel in stems.values():
        p = os.path.join(root, rel)
        with open(p, encoding="utf-8") as f:
            txt = f.read()
        for m in WIKI_RE.finditer(txt):
            t = m.group(1).split("|")[0].split("#")[0].strip().lower()
            if t:
                inbound.add(t)
        for m in MD_LINK_RE.finditer(txt):
            tgt = m.group(1).split("#")[0].strip()
            if tgt.lower().startswith(("http", "mailto")):
                continue
            tgt = tgt.lstrip("./")
            if tgt.endswith(".md"):
                tgt = tgt[:-3]
            if tgt:
                inbound.add(tgt.lower())
    orphans = []
    for key, rel in stems.items():
        base = os.path.basename(key)
        if key in inbound or base in inbound:
            continue
        orphans.append(rel)
    return sorted(orphans)


def main():
    ap = argparse.ArgumentParser(description="文档库巡检")
    ap.add_argument("root", nargs="?", default="docs")
    ap.add_argument("--backend", default="tfidf")
    ap.add_argument("--threshold", type=float, default=None,
                    help="相似度阈值；省略时 tfidf 用 0.55，st/api 用 0.80")
    args = ap.parse_args()
    threshold = args.threshold if args.threshold is not None else (
        0.55 if args.backend == "tfidf" else 0.80)
    root = os.path.join(ROOT, args.root)

    today = date.today().isoformat()
    lines = ["# 文档巡检报告 " + today, ""]

    # 1. doclint 规范校验
    rc, out = run([sys.executable, DOC_PATH, args.root, "--json"])
    lines.append("## 1. 规范校验（doclint）")
    try:
        data = json.loads(out)
        lines.append("- error: %d，warning: %d" % (data["errors"], data["warnings"]))
        for it in data["issues"]:
            if it["severity"] == "error":
                lines.append("  - ❌ [%s] %s" % (it["file"], it["message"]))
        for it in data["issues"]:
            if it["severity"] == "warning":
                lines.append("  - ⚠️ [%s] %s" % (it["file"], it["message"]))
    except Exception:
        lines.append("```\n" + out + "\n```")
    lines.append("")

    # 2. 语义去重
    rc2, out2 = run([sys.executable, DEDUP_PATH, args.root, "--backend", args.backend,
                     "--threshold", str(threshold), "--json"])
    lines.append("## 2. 向量语义去重（dedup, backend=%s）" % args.backend)
    try:
        data = json.loads(out2)
        pairs = data.get("pairs", [])
        lines.append("- 发现 %d 对疑似重复（≥%.2f）：" % (len(pairs), threshold))
        for p in pairs:
            lines.append("  - %.3f  %s  ↔  %s" % (p["similarity"], p["a"], p["b"]))
        if not pairs:
            lines.append("  - 未发现高度相似文档。")
    except Exception:
        lines.append("```\n" + out2 + "\n```")
    lines.append("")

    # 3. 孤儿文档
    orphans = find_orphans(root)
    lines.append("## 3. 孤儿文档（无任何入链）")
    if orphans:
        lines.append("- 共 %d 篇，建议在 Obsidian 图谱中补链接或考虑合并：" % len(orphans))
        for o in orphans:
            lines.append("  - " + o)
    else:
        lines.append("- 无孤儿文档，链接网络连通良好。")
    lines.append("")

    rep_dir = os.path.join(root, ".reports")
    os.makedirs(rep_dir, exist_ok=True)
    rep_path = os.path.join(rep_dir, "inspection-" + today.replace("-", "") + ".md")
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    print("\n报告已写入: " + rep_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
