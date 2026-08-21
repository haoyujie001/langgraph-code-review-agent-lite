"""Model configuration and the Chinese Stage 4 review prompt."""

from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from code_review_agent_lite.config import Settings
from code_review_agent_lite.schemas import ModelReviewResult

REVIEW_SYSTEM_PROMPT = """你是一个只读代码审查助手。
你只能审查用户给出的 Git 变更范围，不要评论未变更的代码。
用户已经提供变更文件和 Diff；信息不足时，可以调用只读工具补充上下文。
不要假设不存在的文件、函数或调用关系。
完成分析后停止调用工具，并用中文给出简洁的审查结论。
系统随后会把你的结论转换成结构化审查结果。"""

STRUCTURE_REVIEW_PROMPT = """请把以上完整审查过程转换成一个 JSON 对象。
严格使用下面的字段结构：
{
  "summary": "中文总结",
  "findings": [
    {
      "path": "变更文件相对路径",
      "line": 1,
      "severity": "low | medium | high | critical",
      "category": "security | bug | performance | maintainability",
      "message": "中文问题描述",
      "suggestion": "中文修复建议"
    }
  ]
}
每个 finding 的六个字段都必须提供，line 必须指向 Diff 中以 + 开头的新增代码行。
只报告有明确代码证据的问题，不要仅因函数缺少非必需的防御性校验而报告问题。
没有明确问题时返回空 findings，不要为了凑数生成问题。只返回 JSON 对象。"""


class ModelConfigurationError(RuntimeError):
    """Raised when the review model cannot be created from settings."""


class ModelInvocationError(RuntimeError):
    """Raised when an external model operation fails at runtime."""


class BoundChatModel(Protocol):
    """Small interface used by the graph after tools have been bound."""

    def invoke(self, messages: list[AnyMessage]) -> AIMessage: ...


class StructuredReviewModel(Protocol):
    """Interface returned by `with_structured_output`."""

    def invoke(self, messages: list[AnyMessage]) -> ModelReviewResult: ...


class ToolCallingModel(Protocol):
    """Small interface shared by ChatOpenAI and scripted test models."""

    def bind_tools(self, tools: Sequence[BaseTool]) -> BoundChatModel: ...

    def with_structured_output(
        self,
        schema: type[ModelReviewResult],
        *,
        method: str,
    ) -> StructuredReviewModel: ...


def create_chat_model(settings: Settings) -> ChatOpenAI:
    """Create the OpenAI-compatible model used by the review node."""

    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value():
        raise ModelConfigurationError(
            "未配置 CODE_REVIEW_LLM_API_KEY，无法调用真实模型。"
        )

    try:
        return ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            max_retries=1,
        )
    except Exception as exc:
        raise ModelConfigurationError("模型配置无效，无法初始化客户端。") from exc
