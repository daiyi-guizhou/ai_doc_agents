---
title: "架构决策记录目录"
type: index
owner: "<填写负责人>"
status: active
review_cycle: 365d
tags: [adr]
updated: 2026-08-05
---

# adr/ — 架构决策记录（Architecture Decision Records）

记录每一个**不可逆**的技术决策：当时面对什么问题、有哪些候选、最终怎么定、为什么。
ADR 一旦 `active` 就**不要改写历史**，推翻旧决策请新开一篇 ADR 并在正文引用它。

- 命名：`NNNN-kebab-slug.md`（序号连续，从 `0001` 起）
- 必须 frontmatter：`type: adr`、`status`、`review_cycle: 365d`
- 用 `draft.py --type adr --title "..."` 生成合规骨架，再补全正文
- 新文档进来先在此登记一行链接（见下方）

## 已登记文档

- [[docs/adr/0001-adopt-markdown-and-adr-for-doc-governance|ADR-0001: 采用 Markdown + ADR 做本地文档治理]]
- [[docs/adr/0002-adopt-multi-agent-pod-framework|ADR-0002: 采用多 Agent Pod 框架编排需求到复盘]]
