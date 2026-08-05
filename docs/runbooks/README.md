---
title: "运维手册目录"
type: index
owner: "<填写负责人>"
status: active
review_cycle: 60d
tags: [runbook]
updated: 2026-08-05
---

# runbooks/ — 运维手册

放**让人能照着操作**的运维文档：部署、回滚、故障排查、on-call 预案、监控告警说明。
这类文档过期代价最高（出事时照着做却错），所以 `review_cycle` 建议最短（60d）。

- 命名：`kebab-slug.md`
- 必须 frontmatter：`type: runbook`
- 每篇开头写明适用环境、前置条件、回滚方式
