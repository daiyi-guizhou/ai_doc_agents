---
name: project-doc-manager
description: 管理 developer_agent 项目本地文档体系（docs/）的完整方法论与工具集。当用户要新建/归档/复核/去重/起草/巡检项目文档、搭建本地 AI 文档治理系统、运行文档校验、接入 Obsidian 看板，或配置 pre-commit 守门时使用。涵盖 ADR/RFC 规范、frontmatter 约定、生命周期状态机、向量语义去重、AI 起草与巡检、Obsidian 双向链接衔接与 git 钩子。
metadata:
  agent_created: true
---

# 项目文档管理（project-doc-manager）

## Overview

把 `developer_agent` 项目的文档做成**本地优先、AI 长期维护、脚本强制守秩序**的体系：
所有文档是仓库里的 Markdown（单一信息源），规范由 `tools/` 下的 Python 脚本变成可执行的检查，
Obsidian 负责可视化与双向链接，git pre-commit 在提交前拦住不合规内容。
本技能既是从零复现该体系的**搭建手册**，也是日常维护的**规则手册**。

## 设计理念（铁律）

1. **单一信息源（SSOT）**：同一件事只写一处，别处用链接引用；接口文档优先自动生成，禁止手写第二份。
2. **规范可执行**：靠脚本（doclint / dedup / inspect）兜底，不靠自觉；warning 与 error 都可视。
3. **不删只标**：废弃内容移到 `archive/`，绝不直接删除。
4. **变更即文档**：上线前补设计；架构改动新增 ADR；事故后写复盘。
5. **AI 维护 + 人看板**：AI 按本技能规则写/校文档；Obsidian 只是可选前端，随时可换。
6. **提交前守门**：pre-commit 跑 doclint --strict，不合规不准进仓库。

## 目录结构（按"文档类型"而非"团队/模块"划分）

| 目录 | type | 内容 | 命名规则 |
|------|------|------|----------|
| `adr/` | adr | 架构决策记录（不可逆决策） | `NNNN-kebab-slug.md`（序号连续，0001 起） |
| `rfcs/` | rfc | 重大变更提案与论证 | `NNNN-kebab-slug.md` |
| `design/` | design | 已落地的系统/模块设计 | `kebab-slug.md` |
| `api/` | api | 接口文档（优先自动生成） | `kebab-slug.md` |
| `runbooks/` | runbook | 部署/回滚/故障排查/on-call | `kebab-slug.md` |
| `guides/` | guide | How-to / onboarding | `kebab-slug.md` |
| `specs/` | spec | 需求 / PRD | `kebab-slug.md` |
| `meetings/` | meeting | 会议纪要 | `YYYY-MM-DD-kebab-slug.md` |
| `agents/` | agent | 多 Agent 框架角色提示词（Pod 系统提示词来源，详见 `docs/agents/README.md`） | `kebab-slug.md`（角色名） |
| `archive/` | deprecated | 已废弃内容的归宿（仅隔离不删） | 保持原名 |
| `.reports/` | — | inspect 生成的巡检报告（gitignore） | `inspection-YYYYMMDD.md` |

每个子目录放一个 `README.md` 作索引，新文档进来先登记一行；各目录放 `_template.md` 供套用。

## 治理规范（frontmatter 强制）

所有**内容文档**（除目录 `README.md` 与 `_template.md` 外）必须开头写：

```yaml
---
title: 文档标题（一句话说清讲什么）
type: design            # adr|rfc|design|api|runbook|guide|spec|meeting
owner: 负责人名          # 对该文档质量负责的人/agent
status: active          # draft|review|active|stale|deprecated
review_cycle: 90d       # 多久复核一次；adr/rfc 建议 365d
tags: [payment, deploy] # 可选
updated: 2026-08-05     # 最后更新日期 YYYY-MM-DD
---
```

**生命周期状态机**：
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
`Active` 超过 `review_cycle` 未更新 → 自动标记 `Stale`（仅预警）；更新回 `Active`，确认过时则 `Deprecated` 移 `archive/`。

## 工具集（tools/，无第三方依赖即可跑校验）

运行用托管 Python：`C:/Users/18862/.workbuddy/binaries/python/versions/3.13.12/python.exe tools/<x>.py`。

### doclint.py — 规范校验（核心守门）
- 校验：必填 frontmatter 字段、type/status 合法性、`adr/rfcs` 序号连续（`NNNN`）、`meetings` 日期前缀、
  内部 Markdown 死链（error）、Obsidian `[[wikilinks]]` 死链（warning）。
- 跳过隐藏目录（`.reports`、`.git` 等），避免误报生成物。
- 命令：
  ```bash
  python tools/doclint.py docs                 # 日常校验
  python tools/doclint.py docs --strict        # 提交前：warning 也阻断（退出码 1）
  python tools/doclint.py docs --json          # JSON 输出，供 inspect 聚合
  python tools/doclint.py docs --today 2027-01-01  # 覆盖今天，测试 stale 预警
  ```

### dedup.py — 向量语义去重
- 抓"字面不同但意思重复"的文档。把每篇文档切成块、向量化、两两算 cosine 相似度，≥阈值报疑似重复对。
- `chunk_text` 剥离 frontmatter/代码块/wikilink；`tokenize` 对中文做**字符 bigram**（CJK）提升词汇相似度。
- 三种后端：
  - `tfidf`（默认，标准库，离线）：词法级近似，阈值默认 **0.55**。
  - `st`（sentence-transformers，真语义）：默认模型 `BAAI/bge-small-zh-v1.5`，阈值 **0.80**。
  - `api`（embedding API）：读环境变量 `EMBED_API_URL` / `EMBED_API_KEY`，阈值 **0.80**。
- `--threshold` 省略时按后端自动取上述默认；`--json` 输出结构化结果。
  ```bash
  python tools/dedup.py docs
  python tools/dedup.py docs --backend st --model BAAI/bge-small-zh-v1.5
  python tools/dedup.py docs --backend api
  ```
- **坑**：tfidf 是词法级，同义改写（零字符重叠，如"账号密码"↔"用户名口令"）只能到 ~0.17，抓不到；
  要抓真语义改写必须用 `--backend st`。

### draft.py — AI 起草脚手架
- 按 `type→目录` 映射生成合规骨架：adr/rfc 自动取下一序号；写 frontmatter（status:draft，
  review_cycle 365d/90d）；并在目录 `README.md` 登记 `[[link|title]]` 一行。
  ```bash
  python tools/draft.py --type adr --title "采用 X 做 Y" [--owner 某人] [--date 2026-08-05] [--root docs]
  ```
- AI 随后补全正文，再跑 doclint 校验。

### inspect.py — 巡检聚合 + 报告
- 汇总 `doclint --json` + `dedup` + **孤儿文档检测**（无任何入链的笔记），输出 `docs/.reports/inspection-YYYYMMDD.md`。
- `--threshold` 同样按后端自适应（修复过原先写死 0.8 导致 tfidf 永远不报重复的 bug）。
  ```bash
  python tools/inspect.py docs
  python tools/inspect.py docs --backend st
  ```

### hooks/pre-commit — 提交前守门（git 钩子）
- 可移植 sh 脚本：Python 发现链 `python3 || python || py`；运行 `doclint --strict`，
  error/warning 阻断提交；环境无 python 时放行（仅告警，不卡死流程）。
- 安装（任选其一）：
  ```bash
  git config core.hooksPath tools/hooks        # 推荐：整目录托管所有 hook
  # 或 cp tools/hooks/pre-commit .git/hooks/pre-commit && chmod +x 之
  ```
- **前提**：项目需已 `git init`。当前 developer_agent 尚未初始化 git，故钩子暂不触发。

## Obsidian 集成（可选 wiki 化前端）

- 把**仓库根目录**（而非仅 docs/）作为 Obsidian vault 打开，这样 `docs/Dashboard.md` 里的 `FROM "docs"` 才正确。
- 安装并启用社区插件 **Dataview**（看板用）、**Templates**（套 `_template.md`）。
- 交叉引用优先用 `[[wikilinks]]`，图谱（Graph）即可可视化文档网络；若文档还要发到不渲染双链的平台，改用普通 Markdown 括号链接，图谱同样识别。
- `docs/Dashboard.md`：Dataview 实时看板（待复核 / 按 owner 分组 / 活跃 ADR / 近期创建）。
- `docs/OBSIDIAN.md`：使用指南。
- `.gitignore` 忽略 `.obsidian/`（个人偏好）与 `docs/.reports/`（生成物）。
- wikilink 解析规则：笔记名按**全相对路径**（去 .md）或 **basename**（去 .md）匹配，小写化；`[[target|别名]]` 取 `|` 前部分匹配。doclint 检测无法解析的 wikilink（warning）。

## 孤儿文档治理（互链约定）

- inspect 的"孤儿文档"= 全库无任何入链的内容文档；Obsidian 图谱里的孤立节点即对应它们。
- 治理动作：在相关文档里加 `[[wikilinks]]` 把孤立节点连进网络，形成连通图。
- 示例三角互链（本项目已落地）：`OBSIDIAN.md` ↔ `Dashboard.md` ↔ `adr/0001-...`，三者互为入链后孤儿数 4→1
  （剩的 1 篇是每次生成的 `inspection-*.md` 报告，属预期，可忽略）。
- 互链要"有意义"而非随便连：ADR 是体系根基、OBSIDIAN 是查看指南、Dashboard 是可视化，彼此引用最自然。

## 每周自动巡检（automation）

- 已配置自动化 `每周文档库巡检`（id `automation-1785938687580`）：
  `rrule = FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0`，状态 ACTIVE，cwd 为项目目录。
- 行为：跑 `tools/inspect.py docs`，把 stale / 孤儿 / 近重复清单总结后推给各 owner。

## 从零复现流程（搭建手册）

1. **建骨架**：按上表建 `docs/` 各子目录，每个放 `README.md`（索引）+ `_template.md`（frontmatter 模板）。
2. **写治理规范**：`docs/README.md` 记录目录结构、frontmatter、类型、状态、生命周期、增强能力（第六章）。
3. **写 doclint.py**：实现 frontmatter/命名/生命周期/死链/wikilink 校验，支持 `--strict/--json/--today`，跳过隐藏目录。
4. **写 dedup.py**：`iter_md` 跳隐藏；`chunk_text` 剥离噪声；`tokenize` 加中文 bigram；`TfidfEmbedder`/`StEmbedder`/`ApiEmbedder`；
   `--threshold` 省略按后端默认（tfidf 0.55 / st·api 0.80）。
5. **写 draft.py + inspect.py**：draft 生成合规骨架并登记目录 README；inspect 聚合三者 + 孤儿检测，写 `.reports/`。
6. **Obsidian 层**：`docs/Dashboard.md`（Dataview）、`docs/OBSIDIAN.md`（指南）、`.gitignore`（忽略 `.obsidian/` 与 `.reports/`）。
7. **配自动化**：建每周一 09:00 跑 inspect 的自动化。
8. **收口**：互链孤儿文档；放 `tools/hooks/pre-commit` 并在 `git init` 后安装；`docs/README.md` 补 6.4 节说明。

## 扩展指南

- **新增文档类型**：改 `doclint.py` 的 `VALID_TYPES`，加对应 `_template.md`、`README.md` 索引行、并在 `docs/README.md` 目录表补一行。
- **换 embedding 后端**：`--backend st`（装 sentence-transformers）或 `--backend api`（配 `EMBED_API_URL`/`EMBED_API_KEY`）。
- **接 CI**：pre-commit 已覆盖本地；若要远端卡，可在 CI 里跑 `python tools/doclint.py docs --strict`。
- **阈值调参**：tfidf 默认 0.55 偏"近重复"；若要更松可显式 `--threshold 0.4`（注意虚报风险）。

## 权威来源 / 参考文件

- 规范：`docs/README.md`
- 工具：`tools/doclint.py`、`tools/dedup.py`、`tools/draft.py`、`tools/inspect.py`、`tools/hooks/pre-commit`
- Obsidian：`docs/Dashboard.md`、`docs/OBSIDIAN.md`、`.gitignore`
- 示例 ADR：`docs/adr/0001-adopt-markdown-and-adr-for-doc-governance.md`

## 常见坑（Gotchas）

- tfidf 抓不到同义改写 → 用 `--backend st`（见 dedup 说明）。
- wikilink 死链在 doclint 里是 **warning**（不阻断常规校验），但 `--strict` 下会阻断。
- doclint / dedup 都跳过 `.` 开头的隐藏目录，生成物（`.reports`）不会污染结果。
- 在 `.workbuddy/` 这种运行时托管目录里手动写文件不稳定（会被重置）；技能/记忆应通过 Skill / 平台机制管理，而非裸写文件。
- 当前项目不是 git 仓库，pre-commit 钩子需先 `git init` 才会生效。
