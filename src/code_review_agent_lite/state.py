"""审查图中各节点共享的状态。"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, TypedDict
from uuid import uuid4

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from code_review_agent_lite.git_service import ChangedFile
from code_review_agent_lite.schemas import Finding, ReviewRequest


class ReviewState(TypedDict):
    """Lite 审查流程的完整状态。"""

    review_id: str
    created_at: datetime
    repo_path: str
    base_ref: str
    head_ref: str
    base_commit: str
    head_commit: str
    review_focus: list[str]
    custom_rules: list[str]
    changed_files: list[ChangedFile]
    diff: str
    added_lines: dict[str, set[int]]
    messages: Annotated[list[AnyMessage], add_messages]
    tool_rounds: int
    tool_calls: int
    findings: list[Finding]
    status: Literal["pending", "completed", "failed"]
    summary: str
    markdown_report: Path | None
    history_saved: bool
    error: str | None


def create_initial_state(request: ReviewRequest) -> ReviewState:
    """将已校验的请求转换为图状态。"""

    return ReviewState(
        review_id=uuid4().hex,
        created_at=datetime.now(UTC),
        repo_path=str(request.repo_path),
        base_ref=request.base_ref,
        head_ref=request.head_ref,
        base_commit="",
        head_commit="",
        review_focus=request.review_focus,
        custom_rules=request.custom_rules,
        changed_files=[],
        diff="",
        added_lines={},
        messages=[],
        tool_rounds=0,
        tool_calls=0,
        findings=[],
        status="pending",
        summary="",
        markdown_report=None,
        history_saved=False,
        error=None,
    )
