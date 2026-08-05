---
title: 文档仪表盘
type: index
owner: AI
status: active
review_cycle: 365d
tags: [dashboard]
updated: 2026-08-05
---

# 📊 文档仪表盘（Obsidian + Dataview）

需要安装并启用 **Dataview** 社区插件。以下查询实时反映 docs/ 的秩序，相当于把
`tools/doclint.py` / `tools/inspect.py` 的离线报告变成**常驻可视化看板**。

> 把本仓库根目录（而非仅 docs/）作为 Obsidian vault 打开，下面的 `FROM "docs"` 才正确。

## 待复核（Stale）
```dataview
TABLE owner, updated, review_cycle FROM "docs" WHERE status = "stale" SORT updated ASC
```

## 按负责人分组的活跃文档
```dataview
TABLE status, updated FROM "docs" WHERE status = "active" SORT owner ASC
```

## 活跃架构决策（ADR）
```dataview
TABLE status, updated FROM "docs/adr" WHERE type = "adr" AND status = "active" SORT file.name ASC
```

## 近期创建
```dataview
TABLE type, status, owner FROM "docs" SORT file.ctime DESC LIMIT 15
```

## 相关文档
- 使用指南（如何把本仓库作为 vault 打开）：[[OBSIDIAN]]
- 体系根基——采用 Markdown + ADR 的决策记录：[[adr/0001-adopt-markdown-and-adr-for-doc-governance|ADR-0001 文档治理规范]]
