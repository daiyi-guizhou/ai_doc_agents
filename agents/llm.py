"""LLM 适配器：OpenAI 兼容协议（标准库 urllib 实现）+ Mock 兜底。

保持零第三方依赖，使其与项目的其它 tools/ 脚本一致。
"""
import json
import urllib.request
import urllib.error
import os
from datetime import date


class LLM:
    """所有 LLM 后端统一的极简协议。"""

    def complete(self, system: str, user: str, temperature: float = 0.3,
                 max_tokens: int = 2000) -> str:
        raise NotImplementedError


class OpenAICompatibleLLM(LLM):
    """调用任意 OpenAI 兼容的 /v1/chat/completions 端点。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def complete(self, system: str, user: str, temperature: float = 0.3,
                 max_tokens: int = 2000) -> str:
        url = self.base_url + "/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            raise RuntimeError(f"LLM 请求失败 [{e.code}]: {body[:500]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"LLM 连接失败: {e.reason}") from e
        return obj["choices"][0]["message"]["content"]


class MockLLM(LLM):
    """离线兜底：不调用任何模型，返回结构化模拟产出，用于验证编排/生命周期。"""

    def complete(self, system: str, user: str, temperature: float = 0.3,
                 max_tokens: int = 2000) -> str:
        prompt_head = system.strip().splitlines()[0] if system.strip() else "(无提示词)"
        # 写文档的 agent：产出一篇符合 doclint 规则的受治理文档（供校验闸门使用）
        if "文档撰写" in system or "角色：documenter" in user or "documenter" in user:
            today = date.today().isoformat()
            return (
                f"---\n"
                f"title: 待办工具设计文档（documenter 模拟产出）\n"
                f"type: design\n"
                f"owner: AI\n"
                f"status: draft\n"
                f"review_cycle: 90d\n"
                f"tags: [design, mock]\n"
                f"updated: {today}\n"
                f"---\n\n"
                f"# 待办工具设计文档\n\n"
                f"本设计由 documenter 基于需求与概要设计产出，覆盖核心模块与接口契约。\n\n"
                f"## 模块\n"
                f"- CLI 入口：解析子命令与参数\n"
                f"- 存储：本地 JSON 文件持久化待办项\n\n"
                f"## 接口契约\n"
                f"- `add(task)` 新增；`done(id)` 完成；`list()` 列出\n\n"
                f"相关框架设计：[[design/multi-agent-pod-framework|多 Agent Pod 框架设计]]\n"
            )
        return (
            f"[MOCK] 角色首行提示词：{prompt_head[:70]}\n"
            f"[MOCK] 收到任务：{user.strip()[:200]}\n"
            f"[MOCK] 本阶段产出（模拟）：已基于上述上下文完成本阶段交付物，"
            f"结论为 PASS，结果可进入下一阶段。\n"
        )
