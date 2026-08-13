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
                 max_tokens: int = 2000, role: "str | None" = None) -> str:
        raise NotImplementedError


class OpenAICompatibleLLM(LLM):
    """调用任意 OpenAI 兼容的 /v1/chat/completions 端点。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def complete(self, system: str, user: str, temperature: float = 0.3,
                 max_tokens: int = 2000, role: "str | None" = None) -> str:
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
    """离线兜底：不调用任何模型，返回结构化模拟产出，用于验证编排/生命周期。

    按角色（role）确定性分支，避免依赖 system/user 里的模糊子串匹配——
    累积上下文里会出现『文档撰写』『验证』等字样，模糊匹配会把后续阶段的
    mock 产出全部误判成 documenter/verifier，导致记录错乱。
    """

    def complete(self, system: str, user: str, temperature: float = 0.3,
                 max_tokens: int = 2000, role: "str | None" = None) -> str:
        # 写文档的 agent：产出一篇符合 doclint 规则的受治理文档（供校验闸门使用）
        if role == "documenter":
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
        # 验证阶段：逐项核验验收标准（从任务文本中的 ACCEPT 块解析），给出可追溯的 PASS
        if role == "verifier":
            import re as _re
            crit = []
            m = _re.search(r"ACCEPT:(.*?)ENDACCEPT", user, _re.DOTALL)
            if m:
                crit = _re.findall(r"^- (.+)$", m.group(1), _re.MULTILINE)
            if not crit:
                crit = ["实现满足需求且测试阶段 PASS"]
            checks = "\n".join(f"- [PASS] {c}" for c in crit)
            return (
                "PASS\n\n"
                "# 验证报告（需求可追溯）\n\n"
                "## 验收标准逐项核验\n" + checks + "\n\n"
                "## 结论\n上述验收标准均已满足，测试阶段 PASS，需求已被实现覆盖，"
                "可进入复盘阶段。\n"
            )
        return (
            f"[MOCK] 角色={role or '?'} 产出（模拟）：已基于上述上下文完成本阶段交付物，"
            f"结论为 PASS，结果可进入下一阶段。\n"
        )
