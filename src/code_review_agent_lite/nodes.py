"""Node functions used by the Lite LangGraph workflow."""

from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from code_review_agent_lite.git_service import ChangedFile, GitService
from code_review_agent_lite.reviewer import (
    REVIEW_SYSTEM_PROMPT,
    STRUCTURE_REVIEW_PROMPT,
    BoundChatModel,
    ModelInvocationError,
    StructuredReviewModel,
)
from code_review_agent_lite.schemas import Finding, ModelReviewResult
from code_review_agent_lite.state import ReviewState

MAX_FINDINGS = 10


def prepare_review(
    state: ReviewState,
    *,
    git_service: GitService,
) -> dict[str, object]:
    """Load Git input and create the first two Agent messages."""

    changed_files = git_service.list_changed_files(
        state["base_ref"],
        state["head_ref"],
    )
    diff, added_lines = git_service.read_diff_with_added_lines(
        state["base_ref"],
        state["head_ref"],
    )
    changed_file_text = (
        "\n".join(
            f"[{changed_file.status}] {changed_file.path}"
            for changed_file in changed_files
        )
        or "（没有变更文件）"
    )
    request_message = (
        "请审查下面的 Git 变更。\n\n"
        f"变更文件：\n{changed_file_text}\n\n"
        f"Diff：\n```diff\n{diff}\n```"
    )
    return {
        "changed_files": changed_files,
        "diff": diff,
        "added_lines": added_lines,
        "messages": [
            SystemMessage(content=REVIEW_SYSTEM_PROMPT),
            HumanMessage(content=request_message),
        ],
    }


def review_agent(
    state: ReviewState,
    *,
    model: BoundChatModel,
) -> dict[str, object]:
    """Ask the model either to call tools or return its final text."""

    try:
        response = model.invoke(state["messages"])
        if not isinstance(response, AIMessage):
            raise TypeError("Review model must return an AIMessage.")
    except Exception as exc:
        raise ModelInvocationError("代码审查模型调用失败，请稍后重试。") from exc
    return {"messages": [response]}


def execute_tools(
    state: ReviewState,
    *,
    tool_node: ToolNode,
) -> dict[str, object]:
    """Execute one model-requested tool batch and count the round."""

    requested_calls = count_requested_tool_calls(state)
    result = tool_node.invoke(state)
    return {
        "messages": result["messages"],
        "tool_rounds": state["tool_rounds"] + 1,
        "tool_calls": state["tool_calls"] + requested_calls,
    }


def structure_review(
    state: ReviewState,
    *,
    model: StructuredReviewModel,
) -> dict[str, object]:
    """Convert the Agent conversation into strict Pydantic output."""

    try:
        result = model.invoke(
            [*state["messages"], HumanMessage(content=STRUCTURE_REVIEW_PROMPT)]
        )
        if not isinstance(result, ModelReviewResult):
            raise TypeError("Structured model must return ModelReviewResult.")
    except Exception as exc:
        raise ModelInvocationError("结构化审查结果生成失败，请稍后重试。") from exc
    findings = validate_findings(
        result.findings,
        state["changed_files"],
        state["added_lines"],
    )
    return {
        "status": "completed",
        "summary": result.summary,
        "findings": findings,
        "error": None,
    }


def stop_review(
    state: ReviewState,
    *,
    max_tool_calls: int,
) -> dict[str, object]:
    """Return a bounded failure before an over-limit tool batch executes."""

    pending_calls = count_requested_tool_calls(state)
    if state["tool_calls"] + pending_calls > max_tool_calls:
        return {
            "status": "failed",
            "summary": "Agent 请求的工具调用总数超过上限，审查被停止。",
            "findings": [],
            "error": "max_tool_calls_exceeded",
        }

    return {
        "status": "failed",
        "summary": "Agent 已达到最大工具调用轮数，审查被停止。",
        "findings": [],
        "error": "max_agent_rounds_exceeded",
    }


def generate_report(
    state: ReviewState,
    *,
    output_dir: Path,
) -> dict[str, object]:
    """Write the final state to one small UTF-8 Markdown report."""

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"review-{uuid4().hex}.md"
    report_path.write_text(render_markdown(state), encoding="utf-8")
    return {"markdown_report": report_path}


def validate_findings(
    candidates: list[Finding],
    changed_files: list[ChangedFile],
    added_lines: dict[str, set[int]],
) -> list[Finding]:
    """Keep added-line findings, remove duplicates, and cap the result."""

    changed_paths = {item.path.replace("\\", "/") for item in changed_files}
    accepted: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()

    for candidate in candidates:
        normalized_path = candidate.path.strip().removeprefix("./").replace("\\", "/")
        if normalized_path not in changed_paths:
            continue
        if candidate.line not in added_lines.get(normalized_path, set()):
            continue

        # The message is part of the key so different problems on one line survive.
        key = (normalized_path, candidate.line, candidate.message.strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        accepted.append(candidate.model_copy(update={"path": normalized_path}))
        if len(accepted) == MAX_FINDINGS:
            break
    return accepted


def count_requested_tool_calls(state: ReviewState) -> int:
    """Count calls in the latest model response without executing them."""

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return 0
    return len(last_message.tool_calls)


def render_markdown(state: ReviewState) -> str:
    """Render one deterministic Markdown document from final graph state."""

    lines = [
        "# 代码审查报告",
        "",
        "## 总结",
        "",
        state["summary"] or "没有生成审查总结。",
        "",
        "## 问题",
        "",
    ]
    if not state["findings"]:
        lines.append("未发现需要报告的问题。")
    else:
        for index, finding in enumerate(state["findings"], start=1):
            lines.extend(
                [
                    f"### {index}. [{finding.severity.value.upper()}] "
                    f"{finding.path}:{finding.line}",
                    "",
                    f"- 类别：`{finding.category.value}`",
                    f"- 问题：{finding.message}",
                    f"- 建议：{finding.suggestion}",
                    "",
                ]
            )
    if state["error"]:
        lines.extend(["", "## 错误", "", f"`{state['error']}`"])
    return "\n".join(lines).rstrip() + "\n"
