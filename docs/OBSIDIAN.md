---
title: 用 Obsidian 打开这套文档
type: guide
owner: AI
status: active
review_cycle: 365d
tags: [obsidian, guide]
updated: 2026-08-05
---

# 用 Obsidian 打开这套文档

本项目的本地文档治理体系（docs/ + AI 工具）与 Obsidian 是天然互补：Obsidian 提供
**双向链接 + 关系图谱**的 wiki 化体验，AI 工具（doclint / dedup / inspect）守住秩序。

## 步骤
1. 打开 Obsidian → **Open folder as vault** → 选择**本项目根目录**（这样 `docs/Dashboard.md`
   里的 `FROM "docs"` 才会正确解析）。
2. 安装并启用社区插件：**Dataview**（仪表盘用）、**Templates**（套用各目录 `_template.md`）。
3. Templates 设置：`Template folder` 指向对应目录（如 `docs/adr`），新建笔记时插入模板。
4. 交叉引用优先用双向链接（双中括号语法）——图谱（Graph）即可可视化文档网络；
   - 纯内部文档可随意用双向链接；
   - 若文档还要发到 GitHub / 网页（不渲染双向链接），改用普通的 Markdown 括号链接写法，图谱同样能识别。
5. 用 `docs/Dashboard.md` 的 Dataview 查询看实时看板：待复核 / 按 owner 分组 / 活跃 ADR。
6. 图谱里的**孤立节点 = 孤儿文档**，配合 `python tools/inspect.py docs` 的孤儿检测一起治理。

## 注意
- `.obsidian/` 是个人偏好，**已 gitignore，不要提交**到仓库。
- 治理仍由外部 AI 工具完成，Obsidian 只是众多前端之一，随时可换（VS Code、GitHub 等都行）。
- wikilink 死链由 `doclint` 检测（warning 级），提交前跑一遍即可发现未创建的链接。

## 相关文档
- 实时看板（Dataview）：[[Dashboard]]
- 体系根基——采用 Markdown + ADR 的决策记录：[[adr/0001-adopt-markdown-and-adr-for-doc-governance|ADR-0001 文档治理规范]]
