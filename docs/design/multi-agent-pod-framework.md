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
| 总控 | `agents/orchestrator.py` | LLM agent：动态决定下一阶段（决策协议 + 门禁 + 回退） |
| 文档校验 | `agents/doclint_check.py` | 把「写文档的 agent」产出交给 `tools/doclint.py` 单篇校验；error 级即 FAIL |
| 沙箱 | `agents/sandbox.py` | developer/tester 的真实执行隔离区：文件 I/O + 白名单命令 + 超时 |
| 工具协议 | `agents/tools.py` | 解析/执行模型的 actions 块（write_file/read_file/list_dir/run） |
| CLI | `agents/cli.py` | `python -m agents run / roles`；`run` 先进入多轮对话澄清需求（人类在环），`--yes` 跳过、`--script` 自动化 |
| 网页界面 | `agents/web.py` + `agents/webui/index.html` | 会话制网页（零依赖 `http.server`）：多对话澄清 + 「开始工作」按钮，确认后写入 `requirements/` 并后台跑 Orchestrator |

## 3. 流水线（Orchestrator 动态编排 + 门禁回退）
七个阶段作为角色目录与兜底顺序（加 `--doc` 时在「概要设计」后插入「文档撰写」）：
```
需求分析 → 概要设计 →[文档撰写]→ 开发 → 测试 → 部署 → 验证 → 复盘
                         ↑_________(FAIL 回退)_________↑
```
- **Orchestrator 是 LLM agent**：每轮读取累积上下文 + 上一阶段门禁结果，输出决策
  `next / rollback / done + role`（见 `agents/orchestrator.py` 的 `decision` 协议），
  由模型动态决定走向，而非写死顺序。Mock 模式用确定性状态机兜底，行为等价于旧管线。
- 门禁阶段：**测试 / 部署 / 验证**，产出须含 `通过/失败` 或 `PASS/FAIL`。
- 门禁 FAIL → 回退到「开发」重做（开发→测试→部署→验证）。
- **文档校验闸门（DOCLINT_ROLES = {documenter}）**：`--doc` 时，文档撰写阶段的产出
  立即交给 `tools/doclint.py` 单篇校验（frontmatter / type / status / 死链）。
  error 级即 FAIL → 把反馈退回 documenter 重做，连续超 `DOCLINT_MAX_RETRY=3` 次判任务失败。
  这把「agent 写出来的文档」和「人维护的文档」约束到同一把尺子（见 `agents/doclint_check.py`）。
- 安全网：请求 `done` 前必须已有一次 验证 PASS（否则强制重跑验证）；
  全局迭代上限 `MAX_ITER=16`，防死循环。
- **验证 PASS 且 复盘完成** → 任务「活干好」。

## 3.1 需求对话澄清（人类在环）
`agents run` 不再是「一句话直接开工」，而是先进入**多轮对话澄清**：AI 主动追问边界 /
范围 / 验收 / 约束，用户逐轮补充，**直到用户显式说『确认 / 开始』**，AI 才把对话汇总成
「需求确认单」（markdown，含原始需求 + 澄清记录 + 执行约定）交给 Orchestrator 开工。
- 澄清助手提示词（SSOT）：`docs/agents/clarifier.md`；离线由 `agents/conversation.py`
  的 `Clarifier` 用确定性追问兜底，保证可演示、可验证。
- 该环节是**人类在环（human-in-the-loop）**的前置交互，不属于 7 阶段流水线本身；
  确认单会成为 [[requirement-analyst|需求分析]] 的输入起点。
- CLI 开关：`--yes` / `-y` 跳过对话直接按给定需求开工；`--script FILE` 从文件逐行读取
  对话输入，便于自动化与回归测试。

## 4. 提示词来源（SSOT）
`docs/agents/` 下每篇 `<role>.md` = 一个角色，frontmatter(`type:agent`)+正文=系统提示词。
新增/调整角色只改文档，框架 `spawn` 时加载，无需改代码。角色与阶段一一对应：
`requirement-analyst / system-designer / documenter / developer / tester / deployer / verifier / retrospector`，
外加 `orchestrator`（总控策略文档，用于注入初始上下文）。其中 `documenter` 为可选阶段，
由 `--doc` 启用，其产出须通过 doclint 校验闸门。

## 5. 产物落库（独立于文档治理）
每次任务在 `agent_runs/<jobid>/` 写入：
- `NN-<role>.md` 各阶段产出（developer/tester 含「沙箱执行记录」）
- `sandbox/` developer/tester 真实写出的文件与命令执行痕迹（随任务留存，便于复盘）
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
python -m agents run                         # 进入对话澄清（多轮），确认后开工
python -m agents run "做一个命令行待办工具"   # 带初始需求进入对话澄清
python -m agents run --mock "..."            # 离线 Mock：对话澄清 + 流水线
python -m agents run --mock --yes "..."      # 跳过对话，直接开工（自动化用）
python -m agents run --mock --script turns.txt   # 从文件逐行读取对话（回归测试）
python -m agents web --mock          # 启动网页版（多对话澄清 + 「开始工作」），默认 http://127.0.0.1:8000
```
> 注：用托管 Python 运行：`C:/Users/18862/.workbuddy/binaries/python/versions/3.13.12/python.exe -m agents ...`

## 8. 后续扩展
- ✅ developer/tester 接沙箱（`agents/sandbox.py` + `agents/tools.py`）：真实读写文件、跑命令，路径穿越/越权/超时三重隔离。
- ✅ Orchestrator 升级为 LLM agent（`decision` 协议动态决定 next/rollback/done），Mock 状态机兜底。
- ✅ 接 `tools/doclint.py` 做「写文档的 agent」产出校验：新增 `documenter` 角色（`--doc` 启用），
  `agents/doclint_check.py` 把其产出单篇校验，error 级即 FAIL → 退回重做，见 `docs/adr/0004-documenter-doclint-gate.md`。
- ✅ `agents run` 改为**对话式需求澄清**（人类在环）：多轮追问边界后由用户确认开工，
  新增 `clarifier` 角色与 `agents/conversation.py`，见 `docs/adr/0005-conversational-requirement.md`。
- ✅ 网页版对话澄清：`agents web` 启动会话制网页（多对话 + 「开始工作」），确认后写入
  `requirements/` 并后台跑 Orchestrator，见 `docs/adr/0006-web-conversational-ui.md`。
- 接 `inspect.py` 巡检。
- 用 `docs/adr/` 记录重大架构变更，用 `docs/runbooks/` 沉淀排障手册。

## 相关文档
- 决策记录：[[adr/0002-adopt-multi-agent-pod-framework|ADR-0002 采用多 Agent Pod 框架]]
- 角色提示词：[[agents/README|Agent 角色提示词库]]
