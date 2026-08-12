---
title: ADR-0006 采用网页版对话澄清界面
type: adr
owner: AI
status: active
review_cycle: 180d
tags: [adr, agents, web, conversation]
updated: 2026-08-12
---

# ADR-0006：采用网页版对话澄清界面

## 状态
采纳（active）— 2026-08-12

## 背景
ADR-0005 已将 `agents run` 改为对话式需求澄清（人类在环），但入口仍是命令行。
用户希望有一个**网页**：在页面上和 AI 多轮对话，确认后写入本地需求文档，并由一个
「开始工作」按钮启动 agent；并且**页面允许同时开多个对话**（不同需求并行澄清）。

约束：项目坚持零第三方依赖（仅 Python 标准库），因此不能引入 Flask / FastAPI / 前端框架。

## 决策
用 **标准库 `http.server`（ThreadingHTTPServer）+ 原生 HTML/CSS/JS 单页**实现：
- 后端 `agents/web.py`：会话制。每个「新建对话」/ 浏览器标签 = 一个 session，服务端在内存
  持有各会话的 `Clarifier` 状态，天然支持**同时多开对话**；用线程锁保护共享状态。
- 接口：`POST /api/sessions`（新建）、`GET /api/sessions`（列表）、
  `GET /api/sessions/<id>`（消息 + 任务摘要）、
  `POST /api/sessions/<id>/message`（对话一步）、
  `POST /api/sessions/<id>/start`（写入需求文档并后台跑 Orchestrator）、
  `GET /api/sessions/<id>/job`（轮询任务状态）。
- 前端 `agents/webui/index.html`：左侧多对话列表（新建/切换），右侧聊天；底部「开始工作」按钮；
  点击后把需求确认单写入 `requirements/`，并定时轮询任务状态，展示各阶段与产物目录。
- 任务在**后台线程**执行（Orchestrator 可能较慢），前端轮询，不阻塞页面。
- 需求文档落 `requirements/<时间戳>-<会话>.md`（已加入 `.gitignore`，作为本地运行时工件）；
  agent 工作依据「该需求文档 + `docs/` 已有文档（SSOT）」开始。

## 后果
- 正向：非技术用户也能用；多需求可并行澄清；确认即落盘，可追溯。
- 负向：引入一个常驻服务进程；需求文档默认不进版本库（`.gitignore`）。
- 风险可控：仅监听 `127.0.0.1`；不暴露任何写权限之外的操作；任务执行复用既有沙箱与门禁。

## 相关文档
- 前置决策：[[0005-conversational-requirement|ADR-0005 对话式需求澄清]]
- 框架设计：[[design/multi-agent-pod-framework|多 Agent Pod 框架设计]]（§3.1、§7）
- 角色提示词：[[agents/clarifier|需求澄清]]
