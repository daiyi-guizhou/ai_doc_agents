---
title: 写文档的 Agent 接入 doclint 产出校验
type: adr
owner: AI
status: active
review_cycle: 365d
tags: [agent, documenter, doclint, governance]
updated: 2026-08-09
---

# ADR-0004 写文档的 Agent 接入 doclint 产出校验

## 状态
active（已实现于 `agents/documenter.md`、`agents/doclint_check.py`、`agents/orchestrator.py`）

## 背景
设计文档 `[[design/multi-agent-pod-framework|多 Agent Pod 框架设计]]` §8 将
"接 `tools/doclint.py` 做「写文档的 agent」产出校验"列为待办。
此前「写文档的 agent」缺位，且即便产出也不受文档治理约束——会出现 frontmatter 缺失、
`type`/`status` 非法、内部死链等不合规文档混进产物，与人维护的文档"两把尺子"。

## 决策
1. **新增 `documenter` 角色**（`docs/agents/documenter.md`，`type: agent`）：概要设计之后、
   开发之前的「文档撰写」阶段，由 `--doc` 开关启用。其提示词明确写出 doclint 契约
   （必填 frontmatter 字段、`type`/`status` 枚举、wikilink 约定），即「提示词即文档」的 SSOT。
2. **新增文档校验闸门**：`agents/doclint_check.py` 把 documenter 的单篇产出交给
   `tools/doclint.py` 在临时目录做 `--json` 单篇校验（flat 放置，不走 adr/rfcs 序号连续性）。
   闸门只看 **error** 级（Obsidian 双链指向 vault 外仅 warning，不致命）。
   - error 级 → FAIL：把 `DocLint.feedback` 退回 documenter 重做（喂反馈改稿）；
   - 连续超 `DOCLINT_MAX_RETRY=3` 次不通过 → 任务判定失败。
3. **Orchestrator 集成**：`DOCLINT_ROLES = {"documenter"}`；阶段执行后若该角色产出校验失败，
   强制 `next=documenter` 重做并附反馈，覆盖模型决策（与门禁 FAIL 回退到开发同级的强制安全网）。

## 备选方案
- **落库后再校验**：先写盘再统一 doclint。缺点：不合规文档已进入产物目录，回退链路更长；
  选"即时单篇校验"让 agent 在同源上下文里就地改稿，反馈闭环最短。
- **另写一套校验规则**：复用 `tools/doclint.py` 而非自造，确保 agent 文档与人维护文档
  共用同一把尺子，治理规则只在一处演进。

## 影响 / 后果
- 正向：「agent 写出来的文档」与「人维护的文档」一致性被强制保证；不合规文档不会流出。
- 约束：仅 `documenter` 角色走此闸门；其余角色产出仍由各自门禁/沙箱约束。
  doclint 缺失或执行异常时闸门降级为"放行 + 告警"，不卡死编排。
- 治理：角色提示词在 `docs/agents/documenter.md` 同步 doclint 契约；
  运行时产物（含每次 documenter 产出 `NN-documenter.md`）落在 `agent_runs/<jobid>/`（已 gitignore）。

## 相关文档
- 框架设计：[[design/multi-agent-pod-framework|多 Agent Pod 框架设计]]
- 校验工具：见 `tools/doclint.py`（产出会经其单篇校验）
- 前置决策：[[adr/0003-sandbox-and-llm-orchestrator|ADR-0003 引入沙箱与 LLM 动态编排]]
- 角色提示词：[[agents/README|Agent 角色提示词库]]
