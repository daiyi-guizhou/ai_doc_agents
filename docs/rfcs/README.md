---
title: "变更提案目录"
type: index
owner: "<填写负责人>"
status: active
review_cycle: 365d
tags: [rfc]
updated: 2026-08-05
---

# rfcs/ — 重大变更提案与论证（Request for Comments）

放**尚未落地**的重大变更提案：背景、方案对比、权衡、风险、预期收益。
通过评审并落地后，对应内容迁到 `design/`（设计）或 `adr/`（已定决策），本目录保留讨论过程。

- 命名：`NNNN-kebab-slug.md`（序号连续，从 `0001` 起）
- 必须 frontmatter：`type: rfc`、`status`、`review_cycle: 365d`
- 用 `draft.py --type rfc --title "..."` 生成合规骨架，再补全正文
- 新文档进来先在此登记一行链接（本目录暂无可登记文档）
