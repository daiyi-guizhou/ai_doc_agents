---
title: "ADR-0001: 采用 Markdown + ADR 做本地文档治理"
type: adr
owner: developer_agent
status: active
review_cycle: 365d
tags: [adr, governance, docs]
updated: 2026-08-05
---

# ADR-0001: 采用 Markdown + ADR 做本地文档治理

## Status
active

## Context
项目文档过去散落、易过期、难追溯；团队需要一个能随项目持续演进、且由 AI 长期维护的本地文档体系。
候选方案：SaaS 知识库（Confluence / Notion / 飞书）、纯文件无规范、以及本方案（本地 Markdown + 治理规范 + 校验脚本）。

## Decision
采用**本地 Markdown 文件 + 统一治理规范 + `doclint.py` 校验脚本**的方案：
- 所有文档放入仓库 `docs/`，按类型分目录；
- 每篇文档带 frontmatter 元数据（owner / status / review_cycle / updated）；
- 不可逆决策写入 `adr/`，用顺序号保留历史；
- 用 `tools/doclint.py` 把规范变成可执行的检查，提交前运行。

## Consequences
- 正：文档与代码同仓、可版本化、可被 AI 与脚本直接读写；无外部平台锁定。
- 负：需要约定与纪律（由技能与脚本兜底）；富媒体（图表）表达弱于 SaaS。
- 已放弃：依赖 SaaS 平台带来的锁定与额外维护成本。

## Related
- 在 Obsidian 中浏览本体系：[[OBSIDIAN]]
- 实时看板（Dataview 可视化）：[[Dashboard]]
