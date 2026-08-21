"""State shared by every node in the review graph."""

from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from code_review_agent_lite.git_service import ChangedFile
from code_review_agent_lite.schemas import Finding, ReviewRequest


class ReviewState(TypedDict):
    """Complete state shape for the Lite review workflow."""

    repo_path: str
    base_ref: str
    head_ref: str
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
    error: str | None


def create_initial_state(request: ReviewRequest) -> ReviewState:
    """Convert a validated HTTP request into an explicit graph state."""

    return ReviewState(
        repo_path=str(request.repo_path),
        base_ref=request.base_ref,
        head_ref=request.head_ref,
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
        error=None,
    )
