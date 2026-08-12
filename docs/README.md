# 项目文档中心（docs）

本目录是 `developer_agent` 项目**所有文档的单一信息源（SSOT）**，由 AI 按 `.workbuddy/skills/project-doc-manager` 中固化的规则长期维护。
目标：在项目持续演进时，文档依然**可发现、可信任、可追溯**。

---

## 一、目录结构（按"文档类型"而非"团队/模块"划分）

模块会变，类型稳定。所有内容按类型归位：

| 目录 | 文档类型 `type` | 内容 | 命名规则 |
|------|----------------|------|----------|
| `adr/` | `adr` | 架构决策记录：每一个**不可逆**的技术决策 | `NNNN-kebab-slug.md`（序号连续，从 0001 起） |
| `rfcs/` | `rfc` | 重大变更提案与论证（未落地前的讨论） | `NNNN-kebab-slug.md` |
| `design/` | `design` | 已落地的系统设计 / 模块设计 | `kebab-slug.md` |
| `api/` | `api` | 接口文档（优先自动生成，禁止手写第二份） | `kebab-slug.md` |
| `runbooks/` | `runbook` | 运维手册：部署 / 回滚 / 故障排查 / on-call | `kebab-slug.md` |
| `guides/` | `guide` | How-to：新人 onboarding、常见操作流程 | `kebab-slug.md` |
| `specs/` | `spec` | 需求 / PRD（按版本或功能归） | `kebab-slug.md` |
| `meetings/` | `meeting` | 会议纪要 | `YYYY-MM-DD-kebab-slug.md` |
| `agents/` | `agent` | 多 Agent 框架角色提示词（Pod 系统提示词来源，详见 `docs/agents/README.md`） | `kebab-slug.md`（角色名） |
| `archive/` | `deprecated` | 已废弃内容的归宿（**不删除**，仅隔离） | 保持原名 |

> 每个子目录下的 `README.md` 是该目录的索引页，新文档进来先在此登记。

---

## 二、每篇文档的元数据（frontmatter，强制）

所有内容文档（除目录 `README.md` 与 `_template.md` 外）必须在开头写：

```yaml
---
title: 文档标题（一句话说清讲什么）
type: design            # 见上表：adr|rfc|design|api|runbook|guide|spec|meeting
owner: 负责人名          # 对该文档质量负责的人
status: active          # draft|review|active|stale|deprecated
review_cycle: 90d       # 多久复核一次；adr 建议 365d
tags: [payment, deploy] # 可选，便于检索
updated: 2026-08-05     # 最后更新日期，YYYY-MM-DD
---
```

---

## 三、文档生命周期（演进项目的兜底机制）

```
Draft ──提交评审──▶ Review ──通过──▶ Active
                                       │  │
                         超期未复核     │  │ 更新并复核
                                       ▼  ▲
                                     Stale
                                       │ 确认过时
                                       ▼
                                  Deprecated ──▶ 移入 archive/
```

- `Active`：`review_cycle` 内未更新 → 自动标记 `Stale`（仅预警，不隐藏）。
- `Stale`：更新并通过复核 → 回到 `Active`；确认过时 → `Deprecated` → 移入 `archive/`。
- 搜索默认隐藏 `Deprecated`；`archive/` 单独隔离，保留历史可追溯。

---

## 四、铁律

1. **单一信息源**：同一件事只写一处，别处用链接引用；接口文档优先自动生成。
2. **变更即文档**：上线前补设计文档；架构改动新增一条 ADR；线上事故后写复盘。
3. **不删只标**：废弃内容移到 `archive/`，绝不直接删除。

---

## 五、AI 如何维护这套文档

- 新建文档：套用对应 `_template.md`，补全 frontmatter，登记到目录 `README.md`。
- 定期复核：运行 `tools/doclint.py`，对 `Stale` 文档提醒 owner 复核或归档。
- 去重 / 死链：doclint 检测内部死链；接入向量检索时可做语义去重。
- 一致性：全部规则来自 `project-doc-manager` 技能，跨会话统一。

运行校验：

```bash
python tools/doclint.py docs
python tools/doclint.py docs --strict   # 提交前用，warning 也阻断
```

---

## 六、增强能力：本地 AI 治理 + Obsidian + 语义去重

### 6.1 Obsidian（wiki 化前端，可选）
把本仓库（或根目录）作为 Obsidian vault 打开即可获得双向链接与关系图谱。
- 交叉引用用 `[[wikilinks]]`，图谱里**孤儿节点一眼可见**（配合巡检的孤儿检测）。
- `docs/Dashboard.md` 用 Dataview 实时看板：待复核 / 按 owner 分组 / 活跃 ADR。
- `.obsidian/` 是个人偏好，已 gitignore，不进仓库；治理仍由外部 AI 工具完成，Obsidian 可随时替换。
- 详见 `docs/OBSIDIAN.md`。`doclint` 已支持 `[[wikilinks]]` 死链检测。

### 6.2 向量语义去重（`tools/dedup.py`）
抓"字面不同但意思重复"的文档——这正是前面聊的"知识向量化"真正有用的落点。
默认 `tfidf` 后端（纯标准库，离线可用，轻量词法近似）；接 `sentence-transformers` 即升级为**真实语义**比对。
```bash
python tools/dedup.py docs
python tools/dedup.py docs --backend st --model BAAI/bge-small-zh-v1.5
```

### 6.3 AI 起草 + 巡检（`tools/draft.py` / `tools/inspect.py`）
- **起草**：`python tools/draft.py --type adr --title "..."` 生成合规脚手架（命名/frontmatter/目录登记），AI 随后补正文。
- **巡检**：`python tools/inspect.py docs` 汇总 doclint 校验 + 语义去重 + **孤儿文档检测**，生成 `docs/.reports/inspection-YYYYMMDD.md`。
- 已配置每周自动巡检（见 `.workbuddy` 自动化），定期把 stale / 孤儿 / 近重复清单推给各 owner。

### 6.4 提交前守门（pre-commit hook，可选）
把 doclint 校验接入 git，提交时自动拦截不合规文档，做到"不合规不准进仓库"。
钩子脚本已就绪：`tools/hooks/pre-commit`（运行 `doclint --strict`，error/warning 均阻断）。

安装（任选其一）：
```bash
# 方式 A：整目录托管所有 hook（推荐）
git config core.hooksPath tools/hooks

# 方式 B：仅安装本 hook
cp tools/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```
> 若环境中没有 python，钩子会放行（仅告警），不会卡死你的提交流程。
> 本项目已 `git init` 并配置 `core.hooksPath tools/hooks`，提交时 doclint 守门自动生效；如未激活，执行 `git config core.hooksPath tools/hooks` 即可。

> 全部规则由 `project-doc-manager` 技能固化，跨会话一致。
