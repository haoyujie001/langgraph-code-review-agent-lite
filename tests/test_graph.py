from pathlib import Path

from conftest import DemoRepository, ScriptedToolCallingModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from code_review_agent_lite.git_service import GitService
from code_review_agent_lite.graph import build_review_graph
from code_review_agent_lite.history import HistoryStore
from code_review_agent_lite.schemas import Finding, ModelReviewResult, ReviewRequest
from code_review_agent_lite.state import create_initial_state
from code_review_agent_lite.tools import build_review_tools


def create_graph(
    demo_repository: DemoRepository,
    allowed_root: Path,
    model: ScriptedToolCallingModel,
    *,
    max_agent_rounds: int = 6,
    max_tool_calls: int = 12,
):
    service = GitService(demo_repository.path, allowed_root)
    tools = build_review_tools(
        service,
        demo_repository.base_sha,
        demo_repository.head_sha,
    )
    return build_review_graph(
        service,
        tools,
        model,
        max_agent_rounds=max_agent_rounds,
        max_tool_calls=max_tool_calls,
        structured_output_method="json_mode",
        output_dir=allowed_root / "reports",
        history_store=HistoryStore(allowed_root / "history"),
    )


def create_state(demo_repository: DemoRepository):
    return create_initial_state(
        ReviewRequest(
            repo_path=demo_repository.path,
            base_ref=demo_repository.base_sha,
            head_ref=demo_repository.head_sha,
        )
    )


def tool_call_message(name: str, arguments: dict[str, str], call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": arguments,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def test_initial_state_contains_message_and_round_fields(tmp_path: Path) -> None:
    state = create_initial_state(
        ReviewRequest(
            repo_path=tmp_path,
            base_ref="main",
            head_ref="feature",
        )
    )

    assert state["messages"] == []
    assert len(state["review_id"]) == 32
    assert state["base_commit"] == ""
    assert state["head_commit"] == ""
    assert state["added_lines"] == {}
    assert state["tool_rounds"] == 0
    assert state["tool_calls"] == 0
    assert state["status"] == "pending"
    assert state["markdown_report"] is None
    assert state["history_saved"] is False


def test_graph_contains_agent_loop_nodes(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    model = ScriptedToolCallingModel([AIMessage(content="完成")])
    graph = create_graph(demo_repository, tmp_path, model)

    drawable_graph = graph.get_graph()

    assert set(drawable_graph.nodes) == {
        "__start__",
        "prepare_review",
        "review_agent",
        "tools",
        "structure_review",
        "stop_review",
        "generate_report",
        "save_history",
        "__end__",
    }
    assert {edge.source for edge in drawable_graph.edges} >= {
        "__start__",
        "prepare_review",
        "review_agent",
        "tools",
        "structure_review",
        "stop_review",
        "generate_report",
        "save_history",
    }


def test_agent_can_finish_without_calling_a_tool(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    model = ScriptedToolCallingModel(
        [AIMessage(content="没有发现需要报告的问题。")],
        ModelReviewResult(summary="没有发现需要报告的问题。", findings=[]),
    )
    graph = create_graph(demo_repository, tmp_path, model)

    result = graph.invoke(create_state(demo_repository))

    assert result["status"] == "completed"
    assert result["summary"] == "没有发现需要报告的问题。"
    assert result["tool_rounds"] == 0
    assert result["findings"] == []
    assert model.bound_tool_names == [
        "list_changed_files",
        "read_diff",
        "read_file",
        "search_code",
    ]
    assert isinstance(result["messages"][0], SystemMessage)
    assert isinstance(result["messages"][1], HumanMessage)
    assert model.structured_output_method == "json_mode"
    assert len(model.structured_received_messages) == 1
    assert result["markdown_report"].is_file()
    assert result["base_commit"] == demo_repository.base_sha
    assert result["head_commit"] == demo_repository.head_sha
    assert (tmp_path / "history" / f"{result['review_id']}.json").is_file()
    assert result["history_saved"] is True
    assert "未发现需要报告的问题" in result["markdown_report"].read_text(
        encoding="utf-8"
    )


def test_custom_rules_are_included_in_the_review_prompt(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    model = ScriptedToolCallingModel([AIMessage(content="完成")])
    graph = create_graph(demo_repository, tmp_path, model)
    request = ReviewRequest(
        repo_path=demo_repository.path,
        base_ref=demo_repository.base_sha,
        head_ref=demo_repository.head_sha,
        review_focus=["安全性"],
        custom_rules=["所有 SQL 必须使用参数化查询"],
    )

    graph.invoke(create_initial_state(request))

    prompt = str(model.received_messages[0][1].content)
    assert "审查重点：安全性" in prompt
    assert "所有 SQL 必须使用参数化查询" in prompt


def test_agent_calls_tool_and_returns_to_model(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    model = ScriptedToolCallingModel(
        [
            tool_call_message(
                "read_file",
                {"path": "src/app.py"},
                "call-read-file",
            ),
            AIMessage(content="发现 SQL 字符串拼接风险。"),
        ],
        ModelReviewResult(
            summary="发现一处高风险 SQL 注入问题。",
            findings=[
                Finding(
                    path="src/app.py",
                    line=5,
                    severity="high",
                    category="security",
                    message="SQL 查询使用了字符串拼接。",
                    suggestion="改用参数化查询。",
                )
            ],
        ),
    )
    graph = create_graph(demo_repository, tmp_path, model)

    result = graph.invoke(create_state(demo_repository))

    assert result["status"] == "completed"
    assert result["summary"] == "发现一处高风险 SQL 注入问题。"
    assert len(result["findings"]) == 1
    assert result["findings"][0].path == "src/app.py"
    assert result["tool_rounds"] == 1
    assert result["tool_calls"] == 1
    assert len(model.received_messages) == 2
    tool_message = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    assert tool_message.name == "read_file"
    assert "def build_query(user_id):" in str(tool_message.content)
    report = result["markdown_report"].read_text(encoding="utf-8")
    assert "[HIGH] src/app.py:5" in report
    assert "改用参数化查询" in report


def test_agent_can_recover_from_invalid_tool_arguments(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    model = ScriptedToolCallingModel(
        [
            tool_call_message("read_file", {"path": "."}, "invalid-path"),
            AIMessage(content="工具参数已修正，审查完成。"),
        ],
        ModelReviewResult(summary="审查完成。", findings=[]),
    )
    graph = create_graph(demo_repository, tmp_path, model)

    result = graph.invoke(create_state(demo_repository))

    assert result["status"] == "completed"
    assert result["tool_rounds"] == 1
    assert result["tool_calls"] == 1
    tool_message = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    assert "工具调用失败" in str(tool_message.content)
    assert "文件路径必须位于仓库内" in str(tool_message.content)


def test_agent_stops_when_maximum_tool_rounds_is_reached(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    model = ScriptedToolCallingModel(
        [
            tool_call_message("read_diff", {}, "call-1"),
            tool_call_message("read_diff", {}, "call-2"),
        ]
    )
    graph = create_graph(
        demo_repository,
        tmp_path,
        model,
        max_agent_rounds=1,
    )

    result = graph.invoke(create_state(demo_repository))

    assert result["status"] == "failed"
    assert result["tool_rounds"] == 1
    assert result["error"] == "max_agent_rounds_exceeded"
    assert "最大工具调用轮数" in result["summary"]
    assert model.structured_received_messages == []
    assert result["markdown_report"].is_file()


def test_agent_rejects_tool_batch_above_total_call_limit(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    model = ScriptedToolCallingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_diff",
                        "args": {},
                        "id": "call-1",
                        "type": "tool_call",
                    },
                    {
                        "name": "read_file",
                        "args": {"path": "src/app.py"},
                        "id": "call-2",
                        "type": "tool_call",
                    },
                ],
            )
        ]
    )
    graph = create_graph(
        demo_repository,
        tmp_path,
        model,
        max_tool_calls=1,
    )

    result = graph.invoke(create_state(demo_repository))

    assert result["status"] == "failed"
    assert result["tool_rounds"] == 0
    assert result["tool_calls"] == 0
    assert result["error"] == "max_tool_calls_exceeded"
    assert "工具调用总数" in result["summary"]
