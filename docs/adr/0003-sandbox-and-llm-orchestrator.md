---
title: 引入沙箱执行与 LLM 动态编排
type: adr
owner: AI
status: active
review_cycle: 180d
tags: [agent, sandbox, orchestrator, architecture]
updated: 2026-08-12
---

# ADR-0003 引入沙箱执行与 LLM 动态编排

## 状态
 active（已实现于 `agents/sandbox.py`、`agents/tools.py`、`agents/orchestrator.py`）

## 背景
多 Agent Pod 框架初版（`[[adr/0002-adopt-multi-agent-pod-framework|ADR-0002]]`）中：
- developer / tester 只生成文本，不真正落地代码、不跑测试；
- Orchestrator 是写死的 7 阶段固定管线，无法按实际情况灵活调度。

设计文档 `[[design/multi-agent-pod-framework|多 Agent Pod 框架设计]]` §8 已将它们列为后续扩展。

## 决策
1. **developer / tester 接沙箱**：新增 `agents/sandbox.py` 提供隔离工作区——
   文件操作限定在沙箱根（路径穿越拒绝），命令执行走 `subprocess(shell=False)`、
   仅白名单可执行文件（python/node/pytest/git 等）、带超时与输出截断。
   模型经 `agents/tools.py` 的 `actions` 协议声明 `write_file/read_file/list_dir/run`，
   Pod 在沙箱内真实执行并回填结果。
2. **Orchestrator 升级为 LLM agent**：改为动态决策——每轮读取累积上下文 + 门禁结果，
   经 `decision` 协议输出 `next / rollback / done + role`，由模型决定下一阶段，
   而非固定顺序。Mock 模式用确定性状态机兜底，行为等价于旧管线，保证离线可验证。

## 备选方案
- **沙箱**：容器/VM 强隔离 vs 进程级软隔离。本地开发 Agent 自测场景下，进程级软隔离
  （路径+白名单+超时）成本低、够用；强隔离作为可替换后端保留接口。
- **编排**：纯静态 DAG vs LLM 动态。选 LLM 动态以贴合「对话发起需求即由 agent 组织
  手下 agent 把活干好」的原始诉求，同时用门禁/最大迭代/强制验证三道安全网兜底。

## 影响 / 后果
- 正向：developer/tester 的产出可被真实执行验证；编排更贴近实际需求，可跳过/重做/回退。
- 负向/约束：沙箱为软隔离，执行不可信代码仍有风险，仅用于本地/受信环境；
  LLM 动态决策依赖模型质量，故保留 Mock 兜底与强制验证安全网。
- 治理：新增角色提示词在 `docs/agents/developer.md`、`tester.md`、`orchestrator.md` 中
  同步说明沙箱能力与决策协议；运行时产物落在 `agent_runs/<jobid>/sandbox/`（已 gitignore）。

## 相关文档
- 框架设计：[[design/multi-agent-pod-framework|多 Agent Pod 框架设计]]
- 初版决策：[[adr/0002-adopt-multi-agent-pod-framework|ADR-0002 采用多 Agent Pod 框架]]
- 角色提示词：[[agents/README|Agent 角色提示词库]]
