---
title: 多 Agent Pod 框架设计
type: design
owner: AI
status: active
review_cycle: 180d
tags: [agent, architecture, design]
updated: 2026-08-12
---

# 多 Agent Pod 框架设计

把 `README.md` 中"用本地文档创建无状态 agent 来开发/运维"的目标，落地为一套
**类 k8s Pod** 的多 Agent 框架：`agents/`（代码） + `docs/agents/`（提示词 SSOT）。

## 1. 设计目标
- **提示词即文档**：角色的 system prompt 存在 `docs/agents/<role>.md`，改角色只改文档。
- **Pod 无状态**：每个 worker 拉起即加载提示词、跑完即销毁，不持有跨任务状态。
- **可编排**：一个总控（Orchestrator）把需求推进过 7 个阶段直到"活干好"。
- **零第三方依赖**：仅用 Python 标准库，与 `tools/` 的治理脚本一致。

## 2. 组件
| 组件 | 文件 | 职责 |
|------|------|------|
| 配置 | `agents/config.py` | 读 `.env`，按环境变量选 LLM 后端（Mock 兜底） |
| LLM 适配器 | `agents/llm.py` | OpenAI 兼容（urllib）/ Mock 两种实现 |
| 提示词仓库 | `agents/prompts.py` | 从 `docs/agents` 加载角色提示词（复用 frontmatter 解析） |
| Pod | `agents/pod.py` | 无状态 worker：`run(task, context)` 一次即销毁 |
| 调度器 | `agents/scheduler.py` | 管理 Pod 生命周期与并发上限 |
| Job | `agents/job.py` | 任务状态机 + 产物落 `agent_runs/<jobid>/` |
| 总控 | `agents/orchestrator.py` | 7 阶段编排、门禁、回退 |
| CLI | `agents/cli.py` | `python -m agents run / roles` |

## 3. 流水线（固定管线 + 门禁回退）
```
需求分析 → 概要设计 → 开发 → 测试 → 部署 → 验证 → 复盘
                         ↑_________(FAIL 回退)_________↑
```
- 门禁阶段：**测试 / 部署 / 验证**，产出须含 `通过/失败` 或 `PASS/FAIL`。
- 门禁 FAIL → 回退到「开发」重做（开发→测试→部署→验证）。
- 全局迭代上限 `MAX_ITER=12`，防死循环。
- **验证 PASS 且 复盘完成** → 任务「活干好」。

## 4. 提示词来源（SSOT）
`docs/agents/` 下每篇 `<role>.md` = 一个角色，frontmatter(`type:agent`)+正文=系统提示词。
新增/调整角色只改文档，框架 `spawn` 时加载，无需改代码。角色与阶段一一对应：
`requirement-analyst / system-designer / developer / tester / deployer / verifier / retrospector`，
外加 `orchestrator`（总控策略文档，用于注入初始上下文）。

## 5. 产物落库（独立于文档治理）
每次任务在 `agent_runs/<jobid>/` 写入：
- `NN-<role>.md` 各阶段产出
- `state.json` 状态机快照
- `SUMMARY.md` 全文汇总
该目录已加入 `.gitignore`（运行时产物，与 docs 治理分离）。

## 6. LLM 后端（可插拔）
- 默认 OpenAI 兼容协议，读 `OPENAI_API_BASE / OPENAI_API_KEY / OPENAI_MODEL`，
  兼容 OpenAI / Azure / vLLM / Ollama 等。
- 缺 key 或 `AGENTS_MOCK=1` → 自动走 `MockLLM`，离线即可跑通编排与生命周期，便于演示与测试。

## 7. 运行
```bash
python -m agents roles                       # 列出可用角色
python -m agents run "做一个命令行待办工具"   # 真实 LLM
python -m agents run --mock "..."            # 离线 Mock 跑通
```
> 注：用托管 Python 运行：`C:/Users/18862/.workbuddy/binaries/python/versions/3.13.12/python.exe -m agents ...`

## 8. 后续扩展
- developer/tester 接沙箱真正读写文件、跑命令（需更高权限）。
- Orchestrator 升级为 LLM agent，动态决定下一阶段（而非固定管线）。
- 接 `tools/doclint.py` 做「写文档的 agent」产出校验；接 `inspect.py` 巡检。
- 用 `docs/adr/` 记录重大架构变更，用 `docs/runbooks/` 沉淀排障手册。

## 相关文档
- 决策记录：[[adr/0002-adopt-multi-agent-pod-framework|ADR-0002 采用多 Agent Pod 框架]]
- 角色提示词：[[agents/README|Agent 角色提示词库]]
