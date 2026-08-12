---
title: Agent 角色提示词库
type: index
owner: AI
status: active
review_cycle: 365d
tags: [agents, prompts]
updated: 2026-08-12
---

# Agent 角色提示词库（docs/agents）

本目录是「多 Agent Pod 框架」的**提示词单一信息源（SSOT）**。
每篇 `<role>.md` 的 frontmatter + 正文 = 该角色 Pod 的系统提示词；
新增 / 调整角色只需改文档，框架在 `spawn` 时从文档加载，无需改代码。

## 角色与阶段映射
- [[requirement-analyst|需求分析]] — 需求拆解与验收标准
- [[system-designer|概要设计]] — 架构与模块设计
- [[developer|开发]] — 编码实现
- [[tester|测试]] — 用例与质量门禁
- [[deployer|部署]] — 上线与回滚
- [[verifier|验证]] — 终验 PASS / FAIL
- [[retrospector|复盘]] — 事后总结
- [[orchestrator|总控策略]] — Orchestrator 的编排与门禁规则

## 相关文档
- 框架设计：[[../design/multi-agent-pod-framework|多 Agent Pod 框架设计]]
- 总体治理：[[../README|文档中心]]
