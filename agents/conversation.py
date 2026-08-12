"""需求对话澄清：把 `agents run` 从『一句话直接开工』升级为『多轮对话澄清后再开工』。

设计要点：
- 人类在环（human-in-the-loop）：AI 主动追问边界 / 范围 / 验收 / 约束，用户逐轮补充；
- 直到用户显式说『确认 / 开始』，AI 才汇总成『需求确认单』并开工；
- 提示词（SSOT）：docs/agents/clarifier.md，使澄清风格可改文档调整、不改代码。

离线（Mock）兜底：无 LLM 时用确定性追问，保证可演示、可验证。
"""
import re

from . import prompts
from .llm import MockLLM

# 确认词：用户在任一轮输入包含这些词即视为『确认完毕，开始工作』。
# 选用多为祈使 / 短词，避免把正常需求描述误判为确认。
_CONFIRM_KEYS = [
    "确认", "开始吧", "可以开始", "就这些", "没问题了", "确定开始",
    "确认开始", "可以了开始", "开工", "go", "start", "ok", "yes", "done",
]


def is_confirm(text: str) -> bool:
    """判断用户这句话是否表示『确认完毕，可以开工』。"""
    if not text:
        return False
    t = text.strip().lower()
    if not t:
        return False
    return any(k in t for k in _CONFIRM_KEYS)


class Clarifier:
    """多轮需求澄清器：管理对话历史，决定下一步追问还是汇总确认单。"""

    def __init__(self, llm, initial: str = None):
        self.llm = llm
        self.history = []            # [(speaker, text)]  speaker ∈ {user, assistant}
        self.requirement = (initial or "").strip()
        self.done = False
        self._spec = ""
        self._pending = ""
        self._asked_boundary = False   # 是否已发出过边界追问
        if self.requirement:
            self.history.append(("user", self.requirement))
        try:
            self.prompt = prompts.load_role("clarifier")["prompt"]
        except Exception:
            self.prompt = (
                "你是需求澄清助手：通过提问帮用户明确需求的边界、范围、验收标准与技术约束，"
                "最终在用户确认后产出『需求确认单』。不要自己开始工作，只负责澄清与汇总。"
            )

    # ---- 对外接口 ----
    def start(self) -> str:
        """返回第一条助手消息（开场白或首轮追问）。"""
        if self.requirement:
            self._pending = self._next_assistant()
        else:
            self._pending = (
                "你好，我是需求澄清助手。请先用一句话告诉我你想做什么，"
                "我会和你确认边界、范围与验收标准，确认无误后再开工。"
            )
        self.history.append(("assistant", self._pending))
        return self._pending

    def submit(self, user_text: str) -> None:
        """接收用户一句话。追加历史；若用户确认则结束并生成 spec。"""
        user_text = (user_text or "").strip()
        if not user_text:
            return
        self.history.append(("user", user_text))
        if not self.requirement:
            self.requirement = user_text   # 首次输入即需求
        if is_confirm(user_text):
            self.done = True
            self._spec = self._synthesize()
            self._pending = ""
            return
        self._pending = self._next_assistant()
        self.history.append(("assistant", self._pending))

    @property
    def pending(self) -> str:
        """待展示给用户的下一条助手消息（确认前）。"""
        return self._pending

    @property
    def spec(self) -> str:
        """已确认的需求确认单（markdown）。"""
        return self._spec

    # ---- 内部 ----
    def _next_assistant(self) -> str:
        if isinstance(self.llm, MockLLM):
            return self._mock_next()
        return self._ask_llm_next()

    def _mock_next(self) -> str:
        """离线兜底：先追问一轮边界，之后给出需求确认单请用户确认。"""
        if not self._asked_boundary:
            self._asked_boundary = True
            return (
                "已收到需求。为确认边界，请补充：① 范围（必须做 / 不必做）"
                "② 技术栈或约束 ③ 验收标准 ④ 优先级。"
                "可逐条回复，或直接回复『确认』按当前理解开工。"
            )
        return (
            "好的，已汇总需求确认单：\n\n```spec\n"
            + self._synthesize()
            + "\n```\n\n如果没问题，请回复『确认』开始工作；如需修改请直接说明。"
        )

    def _ask_llm_next(self) -> str:
        convo = "\n".join(f"{sp}: {tx}" for sp, tx in self.history)
        user = (
            "以下是与用户的对话历史：\n" + convo + "\n\n"
            "请作为需求澄清助手，输出**下一步**要发给用户的话：\n"
            "- 若信息不足，提出 1-2 个具体澄清问题（边界 / 范围 / 验收 / 约束 / 优先级）；\n"
            "- 若信息已较充分，先给出『需求确认单』（用 ```spec 块包裹），再问用户是否确认。\n"
            "不要直接开始工作，只负责澄清与汇总。只输出要发给用户的话。"
        )
        return self.llm.complete(system=self.prompt, user=user)

    def _synthesize(self) -> str:
        qa = "\n".join(f"- {sp}: {tx}" for sp, tx in self.history)
        return (
            "# 需求确认单\n\n"
            f"## 原始需求\n{self.requirement}\n\n"
            "## 澄清记录\n" + qa + "\n\n"
            "## 执行约定\n按上述边界与验收标准推进；边界外内容默认不做，"
            "除非后续明确追加需求。"
        )
