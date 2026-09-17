from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.tools import BaseTool

from code_review_agent_lite.schemas import ModelReviewResult
from scripts.create_demo_repository import DemoRepository, create_demo_repository


class ScriptedToolCallingModel:
    """按预设响应运行的精简确定性模型。"""

    def __init__(
        self,
        responses: list[AIMessage],
        structured_result: ModelReviewResult | None = None,
        *,
        review_error: Exception | None = None,
        structured_error: Exception | None = None,
    ) -> None:
        self.responses = list(responses)
        self.structured_result = structured_result or ModelReviewResult(
            summary="结构化审查完成。",
            findings=[],
        )
        self.bound_tool_names: list[str] = []
        self.received_messages: list[list[AnyMessage]] = []
        self.structured_received_messages: list[list[AnyMessage]] = []
        self.structured_output_method: str | None = None
        self.review_error = review_error
        self.structured_error = structured_error

    def bind_tools(
        self,
        tools: list[BaseTool],
    ) -> ScriptedToolCallingModel:
        self.bound_tool_names = [review_tool.name for review_tool in tools]
        return self

    def invoke(self, messages: list[AnyMessage]) -> AIMessage:
        self.received_messages.append(list(messages))
        if self.review_error is not None:
            raise self.review_error
        if not self.responses:
            raise AssertionError("The scripted model has no response left.")
        return self.responses.pop(0)

    def with_structured_output(
        self,
        schema: type[ModelReviewResult],
        *,
        method: str,
    ) -> ScriptedStructuredReviewModel:
        assert schema is ModelReviewResult
        self.structured_output_method = method
        return ScriptedStructuredReviewModel(self)


class ScriptedStructuredReviewModel:
    """`ScriptedToolCallingModel` 的结构化输出视图。"""

    def __init__(self, parent: ScriptedToolCallingModel) -> None:
        self.parent = parent

    def invoke(self, messages: list[AnyMessage]) -> ModelReviewResult:
        self.parent.structured_received_messages.append(list(messages))
        if self.parent.structured_error is not None:
            raise self.parent.structured_error
        return self.parent.structured_result


@pytest.fixture
def demo_repository(tmp_path: Path) -> DemoRepository:
    """复用演示仓库创建器，使文档与测试共享场景。"""

    return create_demo_repository(tmp_path / "demo-repository")
