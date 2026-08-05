---
title: "RFC 模板"
type: index
owner: "<填写负责人>"
status: active
review_cycle: 180d
tags: [rfc, template]
updated: 2026-08-05
---

# RFC 模板

复制本文件为 `NNNN-kebab-slug.md`（序号取当前 `rfcs/` 最大 +1）。
RFC 用于**重大变更落地前的提案与讨论**，与 ADR 的区别：RFC 是"要不要做 / 怎么做"的论证，ADR 是"已经定了"的记录。

---

```markdown
---
title: "RFC-NNNN: <short title>"
type: rfc
owner: <name>
status: review          # draft|review|active(已采纳)|deprecated(已否决)
review_cycle: 180d
tags: [rfc]
updated: YYYY-MM-DD
---

# RFC-NNNN: <short title>

## Problem
<要解决的问题>

## Proposal
< proposed 方案概述 >

## Alternatives considered
<考虑过但没选的方案及理由>

## Risks
<风险与缓解>
```
