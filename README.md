# ai_doc_agents

用 AI 管理项目文档、知识库、wiki；**而这些文档去创建无状态的 agent 来开发 / 运维**。

本项目包含两套互补能力：

1. **文档治理体系**（`docs/` + `tools/`）：本地优先、脚本强制守秩序，详见 `docs/README.md`
   与技能 `project-doc-manager`。Obsidian 作可选 wiki 前端，git pre-commit 做提交前守门。
2. **多 Agent Pod 框架**（`agents/` + `docs/agents/`）：把文档当作 agent 的提示词来源，
   用类 k8s Pod 的方式编排需求 → 复盘，直到把活干好。

---

## 多 Agent 框架（快速上手）

核心理念：**提示词即文档**。角色的系统提示词写在 `docs/agents/<role>.md`，
框架在拉起 Pod 时从文档加载；改角色只改文档，无需改代码。

### 架构
```
docs/agents/ (提示词 SSOT)
        │ load
        ▼
  Pod 调度器 ──spawn/destroy──▶ 无状态 Agent Pod（按 role 运行一次即销毁）
        ▲
        │ request(role)
  Orchestrator 总控（LLM agent）──动态决定下一阶段──▶ 需求分析→…→复盘
                                              │(门禁 FAIL 强制回退到开发)
        │ write
        ▼
  agent_runs/<jobid>/  (产物：各阶段 .md + state.json + SUMMARY.md)
```

### 运行（使用托管 Python）
```bash
PY="C:/Users/18862/.workbuddy/binaries/python/versions/3.13.12/python.exe"

$PY -m agents roles                        # 列出可用角色（来自 docs/agents）
$PY -m agents run "做一个命令行待办工具"    # 真实 LLM（需配置 .env）
$PY -m agents run --mock "..."             # 离线 Mock 跑通编排与生命周期
$PY -m agents run --mock --no-sandbox "..." # 关闭沙箱（dev/tester 退回纯文本）
```

### LLM 后端（可插拔）
- 默认 OpenAI 兼容协议，读 `OPENAI_API_BASE / OPENAI_API_KEY / OPENAI_MODEL`
  （兼容 OpenAI / Azure / vLLM / Ollama）。
- 缺 key 或 `AGENTS_MOCK=1` → 自动走 `MockLLM`，离线即可跑通全流程。

### 沙箱与真实执行
- `developer` / `tester` 在 `agent_runs/<jobid>/sandbox/` 内**真实读写文件、跑命令**
  （`agents/sandbox.py` 做路径穿越拦截 + 命令白名单 + 超时；`agents/tools.py` 解析模型的
  `actions` 协议）。其余角色仍为纯文本生成。
- 关闭：`--no-sandbox`。

### Orchestrator 是 LLM agent
- 不再写死管线：每轮读取「累积上下文 + 上一阶段门禁结果」，输出 `decision`
  （`next / rollback / done + role`），由模型动态决定走向；Mock 用确定性状态机兜底。
- 安全网：门禁 FAIL **强制**回退到开发；请求 `done` 前必须已有一次验证 PASS；
  超过 `MAX_ITER` 判定失败，防死循环。

配置样例见 `.env.example`（复制为 `.env` 后填写）。

### 文档与角色
- 角色提示词：`docs/agents/`（共 8 篇：orchestrator + 7 个阶段角色）
- 框架设计：`docs/design/multi-agent-pod-framework.md`
- 决策记录：`docs/adr/0002-adopt-multi-agent-pod-framework.md`

---

## 文档治理（概要）
- 校验：`python tools/doclint.py docs`（提交前用 `--strict`，warning 也阻断）
- 去重：`python tools/dedup.py docs`
- 起草：`python tools/draft.py --type adr --title "..."`
- 巡检：`python tools/inspect.py docs`（已配每周自动巡检）
- 看板：用 Obsidian 打开本仓库根目录，`docs/Dashboard.md` 提供 Dataview 实时看板

### Git 提交守门（已生效）
- 项目已 `git init`，并通过 `git config core.hooksPath tools/hooks` 激活
  `tools/hooks/pre-commit`：每次提交前自动跑 `doclint --strict`，文档秩序不达标则阻断提交。
- 已验证：不合规文档会被拦截，合规文档可正常提交。
