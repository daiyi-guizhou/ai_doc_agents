---
title: ADR-0005 采用对话式需求澄清（人类在环）
type: adr
owner: AI
status: active
review_cycle: 180d
tags: [adr, agents, conversation, human-in-the-loop]
updated: 2026-08-12
---

# ADR-0005：采用对话式需求澄清（人类在环）

## 状态
采纳（active）— 2026-08-12

## 背景
此前 `agents run "<需求>"` 把整句需求直接作为 Orchestrator 的输入，立即开工。
问题在于：用户常只用一句话描述，缺少边界、范围、验收标准与约束；框架只能凭模糊需求硬跑，
容易跑偏、反复回退，浪费阶段迭代。

与此同时，框架已具备「提示词即文档」的 SSOT 体系与 doclint 治理，新增一个「澄清助手」
角色成本很低，且应与现有角色一样由 `docs/agents/` 驱动。

## 决策
把 `agents run` 改为**对话式需求澄清**入口：
- 进入多轮对话：AI（澄清助手）主动追问边界 / 范围 / 验收 / 约束，用户逐轮补充；
- **人类在环（human-in-the-loop）**：只有当用户显式说「确认 / 开始」，AI 才把对话汇总为
  「需求确认单」（markdown：原始需求 + 澄清记录 + 执行约定）交给 Orchestrator 开工；
- 澄清助手提示词（SSOT）：`docs/agents/clarifier.md`；离线由 `agents/conversation.py`
  的 `Clarifier` 用确定性追问兜底，保证可演示、可验证；
- CLI 开关：`--yes` / `-y` 跳过对话直接按给定需求开工（自动化用）；
  `--script FILE` 从文件逐行读取对话输入，便于回归测试；
- 该环节是流水线前的**前置交互**，不属于 7 阶段本身；确认单作为
  [[agents/requirement-analyst|需求分析]] 的输入起点。

## 后果
- 正向：需求更清晰，阶段回退减少；人类始终掌握「何时开工」的控制权；
  风格可改 `clarifier.md` 调整、不改代码。
- 负向：多了一道交互，简单一次性任务需多打几行；自动化场景须用 `--yes` 或 `--script`。
- 风险可控：对话环节不做任何写操作，仅产出文本确认单，不影响沙箱与文档治理。

## 相关文档
- 框架设计：[[design/multi-agent-pod-framework|多 Agent Pod 框架设计]]（§3.1）
- 角色提示词：[[agents/clarifier|需求澄清]]、[[agents/README|Agent 角色提示词库]]
- 前置决策：[[0002-adopt-multi-agent-pod-framework|ADR-0002 采用多 Agent Pod 框架]]
