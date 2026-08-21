"""Graph construction and conditional routing for the Lite Agent."""

from functools import partial
from pathlib import Path
from typing import Literal

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from code_review_agent_lite.git_service import GitService
from code_review_agent_lite.nodes import (
    count_requested_tool_calls,
    execute_tools,
    generate_report,
    prepare_review,
    review_agent,
    stop_review,
    structure_review,
)
from code_review_agent_lite.reviewer import ModelInvocationError, ToolCallingModel
from code_review_agent_lite.schemas import ModelReviewResult
from code_review_agent_lite.state import ReviewState


def route_after_agent(
    state: ReviewState,
    *,
    max_agent_rounds: int,
    max_tool_calls: int,
) -> Literal["tools", "structure_review", "stop_review"]:
    """Choose another tool round, structured finalization, or a bounded stop."""

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # Reject the complete batch before ToolNode executes any over-limit call.
        pending_calls = count_requested_tool_calls(state)
        if state["tool_calls"] + pending_calls > max_tool_calls:
            return "stop_review"
        if state["tool_rounds"] < max_agent_rounds:
            return "tools"
        return "stop_review"
    return "structure_review"


def build_review_graph(
    git_service: GitService,
    tools: list[BaseTool],
    model: ToolCallingModel,
    *,
    max_agent_rounds: int,
    max_tool_calls: int,
    structured_output_method: str,
    output_dir: Path,
):
    """Compile one request-scoped Agent graph."""

    try:
        bound_model = model.bind_tools(tools)
        structured_model = model.with_structured_output(
            ModelReviewResult,
            method=structured_output_method,
        )
    except Exception as exc:
        raise ModelInvocationError("审查模型初始化失败，请检查模型配置。") from exc
    tool_node = ToolNode(tools)
    builder = StateGraph(ReviewState)

    builder.add_node("prepare_review", partial(prepare_review, git_service=git_service))
    builder.add_node("review_agent", partial(review_agent, model=bound_model))
    # ToolNode is wrapped only to add the visible tool-round counter.
    builder.add_node("tools", partial(execute_tools, tool_node=tool_node))
    builder.add_node(
        "structure_review",
        partial(structure_review, model=structured_model),
    )
    builder.add_node(
        "stop_review",
        partial(stop_review, max_tool_calls=max_tool_calls),
    )
    builder.add_node(
        "generate_report",
        partial(generate_report, output_dir=output_dir),
    )

    builder.add_edge(START, "prepare_review")
    builder.add_edge("prepare_review", "review_agent")
    builder.add_conditional_edges(
        "review_agent",
        partial(
            route_after_agent,
            max_agent_rounds=max_agent_rounds,
            max_tool_calls=max_tool_calls,
        ),
        {
            "tools": "tools",
            "structure_review": "structure_review",
            "stop_review": "stop_review",
        },
    )
    builder.add_edge("tools", "review_agent")
    builder.add_edge("structure_review", "generate_report")
    builder.add_edge("stop_review", "generate_report")
    builder.add_edge("generate_report", END)
    return builder.compile()
