---
name: project-doc-manager
description: 管理 developer_agent 项目本地文档体系（docs/）。当用户要新建/归档/复核/去重/起草/巡检项目文档，或运行文档校验时使用。涵盖 ADR/RFC 规范、frontmatter 约定、生命周期、Obsidian 衔接、向量语义去重与 AI 起草巡检。
---

# 项目文档管理（project-doc-manager）

本技能固化 `developer_agent` 项目文档体系的治理规则，使 AI 在任意会话中按同一套约定维护**本地 Markdown 文档**。目标是：项目持续演进时，文档依然可发现、可信任、可追溯。

## 权威来源
- 完整规范：`docs/README.md`（目录结构、frontmatter、类型、状态、生命周期、增强能力）。
- 校验工具：`tools/doclint.py`（无第三方依赖，托管 Python 运行）。
- 语义去重：`tools/dedup.py`；起草脚手架：`tools/draft.py`；巡检：`tools/inspect.py`。
- Obsidian 衔接指南：`docs/OBSIDIAN.md`；实时看板：`docs/Dashboard.md`（Dataview）。

## 何时使用
- 用户要新建任何项目文档（adr / rfc / design / api / runbook / guide / spec / meeting）。
- 需要归档、复盘、复核、去重、起草、巡检、修复死链或检查文档秩序。
- 任何形式的"项目文档怎么放 / 合不合规 / 怎么用 Obsidian 看"的询问。

## 核心规则（务必遵守）
1. 每篇**内容文档**必须有 frontmatter：`title, type, owner, status, updated`（必填）；`review_cycle, tags`（可选）。`README.md` 与 `_template.md` 豁免。
2. `type` ∈ {adr, rfc, design, api, runbook, guide, spec, meeting, index}；`status` ∈ {draft, review, active, stale, deprecated}。
3. `adr/` 与 `rfcs/` 文件命名 `NNNN-slug.md`，序号连续从 0001；`meetings/` 命名 `YYYY-MM-DD-slug.md`。
4. 新建先复制对应 `_template.md`，填写后再在目录 `README.md` 登记一行链接。
5. 不可逆决策写 ADR；重大提案写 RFC；废弃内容移到 `archive/`，**绝不删除**。
6. 单一信息源：接口文档优先自动生成，禁止手写第二份；别处用链接引用，不复制。
7. 交叉引用可用 `[[wikilinks]]`（Obsidian 友好）或 `[](path.md)`；doclint 会检测两类死链。

## 工作流程
- **新建 / 起草**：运行 `python tools/draft.py --type <t> --title "..." [--owner X]` 生成合规脚手架（自动命名、填 frontmatter、在目录 README 登记），随后 AI 补全正文，再跑 doclint。也可手动复制 `_template.md`。
- **复核**：运行 `python tools/doclint.py docs`；对 `stale` 文档提醒 owner 复核（更新 `updated` 回到 `active`）或标 `deprecated` 并移 `archive/`。
- **语义去重**：运行 `python tools/dedup.py docs`（默认 tfidf 离线；`--backend st` 升级真实语义）。对高相似度文档对建议合并或互链。
- **巡检**：运行 `python tools/inspect.py docs`，汇总规范校验 + 近重复 + **孤儿文档**，产出 `docs/.reports/inspection-YYYYMMDD.md`。每周有自动巡检自动化兜底。
- **Obsidian**：把仓库根目录作为 vault 打开；用 `docs/Dashboard.md` 看实时看板；图谱孤立节点对应孤儿文档。

## 运行命令
```bash
python tools/doclint.py docs                 # 日常校验
python tools/doclint.py docs --strict        # 提交前：warning 也阻断
python tools/doclint.py docs --json          # JSON 输出（inspect 用）
python tools/dedup.py docs                   # 向量语义去重（tfidf 离线）
python tools/dedup.py docs --backend st      # 真实语义（需 sentence-transformers）
python tools/draft.py --type adr --title "..."   # 起草脚手架
python tools/inspect.py docs                 # 巡检并生成报告
```
