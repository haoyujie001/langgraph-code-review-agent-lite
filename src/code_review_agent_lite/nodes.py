"""Lite LangGraph 工作流的节点函数。"""

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from code_review_agent_lite.git_service import ChangedFile, GitService
from code_review_agent_lite.history import HistoryStore
from code_review_agent_lite.reviewer import (
    REVIEW_SYSTEM_PROMPT,
    STRUCTURE_REVIEW_PROMPT,
    BoundChatModel,
    ModelInvocationError,
    StructuredReviewModel,
)
from code_review_agent_lite.schemas import Finding, ModelReviewResult
from code_review_agent_lite.state import ReviewState

MAX_FINDINGS = 10 #模型最多可以返回 20 条候选问题，但经过过滤后，最终最多接受 10 条。


def prepare_review(
    state: ReviewState,
    *,
    git_service: GitService,
) -> dict[str, object]:
    """加载 Git 输入并创建前两条 Agent 消息。"""

    base_commit, head_commit = git_service.resolve_range(
        state["base_ref"],
        state["head_ref"],
    )
    changed_files = git_service.list_changed_files(
        base_commit,
        head_commit,
    )
    diff, added_lines = git_service.read_diff_with_added_lines(
        base_commit,
        head_commit,
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
        f"提交范围：{base_commit}..{head_commit}\n\n"
        f"{render_review_criteria(state)}\n\n"
        f"变更文件：\n{changed_file_text}\n\n"
        f"Diff：\n```diff\n{diff}\n```"
    )
    return {
        "base_commit": base_commit,
        "head_commit": head_commit,
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
    """让模型调用工具或返回最终文本。"""

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
    """执行一批模型工具调用并记录轮次。"""

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
    """ 将 Agent 对话转换为严格的 Pydantic 输出。"""

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
    """在执行超限工具批次前返回失败结果。"""

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
    """将最终状态写入 UTF-8 Markdown 报告。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"review-{state['review_id']}.md"
    report_path.write_text(render_markdown(state), encoding="utf-8")
    return {"markdown_report": report_path}


def save_history(
    state: ReviewState,
    *,
    history_store: HistoryStore,
) -> dict[str, object]:
    """报告生成后保存审查历史。"""

    history_store.save_state(state)
    return {"history_saved": True}

#########################################
def validate_findings(
    candidates: list[Finding],
    changed_files: list[ChangedFile],
    added_lines: dict[str, set[int]],
) -> list[Finding]:
    """保留新增行问题、去重并限制数量。"""

    changed_paths = {item.path.replace("\\", "/") for item in changed_files}
    accepted: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()

    for candidate in candidates:
        normalized_path = candidate.path.strip().removeprefix("./").replace("\\", "/")
        if normalized_path not in changed_paths:
            continue
        if candidate.line not in added_lines.get(normalized_path, set()):
            continue

        # 将描述纳入键中，以保留同一行的不同问题。
        key = (normalized_path, candidate.line, candidate.message.strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        accepted.append(candidate.model_copy(update={"path": normalized_path}))
        if len(accepted) == MAX_FINDINGS:
            break
    return accepted


def count_requested_tool_calls(state: ReviewState) -> int:
    """最新一次回复中，请求调用了多少个工具"""

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return 0
    return len(last_message.tool_calls)


def render_markdown(state: ReviewState) -> str:
    """根据最终图状态渲染确定性 Markdown。"""

    lines = [
        "# 代码审查报告",
        "",
        "## 审查信息",
        "",
        f"- 审查 ID：`{state['review_id']}`",
        f"- Commit Range：`{state['base_commit']}..{state['head_commit']}`",
        f"- 变更文件数：{len(state['changed_files'])}",
        "",
        "## 审查标准",
        "",
        render_review_criteria(state),
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


def render_review_criteria(state: ReviewState) -> str:
    """为提示词和报告渲染有界审查标准。"""

    lines: list[str] = []
    if state["review_focus"]:
        lines.append("审查重点：" + "、".join(state["review_focus"]))
    if state["custom_rules"]:
        lines.append("自定义规则：")
        lines.extend(f"- {rule}" for rule in state["custom_rules"])
    return "\n".join(lines) or "使用默认审查标准。"
