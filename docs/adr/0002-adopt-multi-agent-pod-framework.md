---
title: 采用多 Agent Pod 框架编排「需求→复盘」
type: adr
owner: AI
status: active
review_cycle: 365d
tags: [agent, architecture, adr]
updated: 2026-08-12
---

# ADR-0002: 采用多 Agent Pod 框架编排「需求 → 复盘」

## 状态
Active（已落地于 `agents/` 与 `docs/agents/`）。

## 背景（Context）
`README.md` 既定目标：用本地管理的文档（wiki + Obsidian）去创建**无状态**的 agent
来开发 / 运维。但项目此前只有文档治理（`tools/` + `docs/`），没有任何"让 agent 真正干活"
的运行框架。需要在不破坏现有文档治理体系的前提下，补一套多 Agent 编排能力。

约束：
- 提示词必须来自当前本地文档（SSOT，符合项目铁律）。
- 尽量零第三方依赖，与既有 `tools/` 脚本一致，便于长期维护。
- 需可在无 LLM key 的环境离线验证架构。

## 决策（Decision）
采用**类 k8s Pod** 模型：
1. 角色提示词存 `docs/agents/<role>.md`（受 doclint 治理、Obsidian 可见），框架 `spawn` 时加载。
2. `Scheduler` 管理无状态 `Pod` 的拉起 / 销毁；`Pod` 跑完即弃，不持有跨任务状态。
3. `Orchestrator` 以固定 7 阶段管线（需求分析→概要设计→开发→测试→部署→验证→复盘）
   驱动，门禁阶段 FAIL 回退到「开发」重做，验证 PASS 且复盘完成即判定"活干好"。
4. 任务产物落 `agent_runs/<jobid>/`（独立于 `docs/` 治理，已 gitignore）。
5. LLM 后端可插拔：OpenAI 兼容协议（urllib 实现）+ `MockLLM` 兜底。

## 候选方案（Alternatives Considered）
- **A. 直接复用 WorkBuddy 的 Agent 工具做子 agent**：最快，但框架不独立、不可在
  项目内单独运行，且提示词来源仍游离于文档治理之外。否决。
- **B. 纯 LLM-agent 动态编排（无固定管线）**：更灵活，但不可控、易死循环、难测试。
  暂采用固定管线 + 门禁回退，后续可把 Orchestrator 升级为 LLM agent（见设计文档 §8）。
- **C. 把产物也写进 `docs/runs/`**：更统一，但会污染文档类型治理与 Obsidian 图谱。
  按用户选择落到独立 `agent_runs/`。

## 后果（Consequences）
- 正面：提示词与文档治理统一；Pod 无状态易扩展；零依赖易维护；可离线演示。
- 负面 / 待办：当前 Orchestrator 是确定性管线，非 LLM 自主规划；developer/tester
  尚只生成文本、未接入真实文件系统与命令执行（需沙箱与权限）；未 `git init`，
  `tools/hooks/pre-commit` 守门仍不生效。

## 相关文档
- 设计：[[multi-agent-pod-framework|多 Agent Pod 框架设计]]
- 根基：[[0001-adopt-markdown-and-adr-for-doc-governance|ADR-0001 文档治理规范]]
- 角色提示词：[[agents/README|Agent 角色提示词库]]
