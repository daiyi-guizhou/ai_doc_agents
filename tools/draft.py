#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""draft - 按规范为新文档生成脚手架（AI 起草的第一步）。

生成正确命名、合规 frontmatter（含今天日期）和章节骨架，并在目录 README.md 登记一行。
AI 随后填充正文内容，再跑 doclint 校验即可。

用法：
  python tools/draft.py --type adr --title "采用 PostgreSQL 替代 MySQL"
  python tools/draft.py --type runbook --title "支付服务部署手册" --owner 张工
  python tools/draft.py --type meeting --title "周会" --date 2026-08-12
"""
import argparse
import os
import re
import sys
from datetime import date

TYPE_DIR = {
    "adr": "adr", "rfc": "rfcs", "design": "design", "api": "api",
    "runbook": "runbooks", "guide": "guides", "spec": "specs", "meeting": "meetings",
}
SEQ_TYPES = {"adr", "rfc"}
EXEMPT = {"README.md", "_template.md"}
SEQ_RE = re.compile(r"^(\d{4})-.*\.md$")


def slugify(title):
    s = re.sub(r"[^\w一-鿿]+", "-", title.lower()).strip("-")
    return s[:60] or "untitled"


def next_seq(d):
    nums = []
    if os.path.isdir(d):
        for fn in os.listdir(d):
            m = SEQ_RE.match(fn)
            if m:
                nums.append(int(m.group(1)))
    return "%04d" % ((max(nums) if nums else 0) + 1)


def body_for(t):
    if t == "adr":
        return ("## Status\nactive\n\n## Context\n<问题是什么 / 面临哪些约束与力量>\n\n"
                "## Decision\n<我们决定怎么做>\n\n## Consequences\n<正面与负面后果；放弃了什么>\n")
    if t == "rfc":
        return ("## 动机\n<为什么做>\n\n## 方案\n<怎么做>\n\n"
                "## 权衡\n<取舍与备选方案>\n\n## 影响\n<对系统/团队的影响>\n")
    if t == "meeting":
        return "## 参会人\n\n## 议题\n\n## 决议 / 待办\n\n"
    return ("## 概述\n<一句话说明本文档讲什么>\n\n## 内容\n\n## 参考\n\n")


def register(dir_readme, link):
    if not os.path.isfile(dir_readme):
        with open(dir_readme, "w", encoding="utf-8") as f:
            f.write("# 目录索引\n\n")
    with open(dir_readme, encoding="utf-8") as f:
        content = f.read()
    if link not in content:
        with open(dir_readme, "a", encoding="utf-8") as f:
            f.write(link + "\n")


def main():
    ap = argparse.ArgumentParser(description="生成新文档脚手架")
    ap.add_argument("--type", required=True, choices=list(TYPE_DIR))
    ap.add_argument("--title", required=True)
    ap.add_argument("--owner", default="<填写负责人>")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    ap.add_argument("--root", default="docs")
    args = ap.parse_args()

    today = args.date or date.today().isoformat()
    d = os.path.join(args.root, TYPE_DIR[args.type])
    os.makedirs(d, exist_ok=True)
    slug = slugify(args.title)

    if args.type in SEQ_TYPES:
        fname = "%s-%s.md" % (next_seq(d), slug)
    elif args.type == "meeting":
        fname = "%s-%s.md" % (today, slug)
    else:
        fname = "%s.md" % slug

    path = os.path.join(d, fname)
    if os.path.exists(path):
        print("文件已存在: " + path)
        return 1

    rc = "365d" if args.type in ("adr", "rfc") else "90d"
    fm = (
        "---\n"
        'title: "%s"\n'
        "type: %s\n"
        "owner: %s\n"
        "status: draft\n"
        "review_cycle: %s\n"
        "tags: [%s]\n"
        "updated: %s\n"
        "---\n\n"
        "# %s\n\n%s"
    ) % (args.title, args.type, args.owner, rc, args.type, today, args.title, body_for(args.type))

    with open(path, "w", encoding="utf-8") as f:
        f.write(fm)

    rel = os.path.relpath(path, args.root).replace("\\", "/")
    register(os.path.join(d, "README.md"), "- [[%s|%s]]" % (rel, args.title))

    print("已创建草稿: " + path)
    print("请在 AI 协助下补全正文，然后运行: python tools/doclint.py " + args.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
