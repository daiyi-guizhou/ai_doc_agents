"""配置加载：.env 解析 + LLM 后端选择（可插拔适配器 + Mock 兜底）。

无任何第三方依赖；.env 用极简自写解析器读取，避免引入 python-dotenv。
LLM 后端决策：
  - 显式 AGENTS_MOCK=1，或缺少 OPENAI_API_KEY  → 使用 MockLLM（离线可跑通编排）
  - 否则                                          → OpenAI 兼容端点（兼容 OpenAI/Azure/vLLM/Ollama）
"""
import os

from .llm import MockLLM, OpenAICompatibleLLM


def load_dotenv(path=".env"):
    """极简 .env 读取：仅 setdefault，不覆盖已存在的环境变量。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"\'')
            if key:
                os.environ.setdefault(key, val)


def get_llm():
    """按环境变量返回 LLM 适配器实例。"""
    if os.environ.get("AGENTS_MOCK") == "1" or not os.environ.get("OPENAI_API_KEY"):
        return MockLLM()
    return OpenAICompatibleLLM(
        base_url=os.environ.get("OPENAI_API_BASE", "https://api.openai.com").rstrip("/"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    )


def is_mock():
    return os.environ.get("AGENTS_MOCK") == "1" or not os.environ.get("OPENAI_API_KEY")
