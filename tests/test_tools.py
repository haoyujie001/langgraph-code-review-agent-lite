from pathlib import Path

import pytest
from conftest import DemoRepository
from langchain_core.tools import BaseTool

from code_review_agent_lite.git_service import GitService, GitServiceError
from code_review_agent_lite.tools import build_review_tools


@pytest.fixture
def review_tools(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> dict[str, BaseTool]:
    service = GitService(
        repo_path=demo_repository.path,
        allowed_repo_root=tmp_path,
    )
    tools = build_review_tools(
        service,
        demo_repository.base_sha,
        demo_repository.head_sha,
    )
    return {review_tool.name: review_tool for review_tool in tools}


def test_build_review_tools_exposes_exactly_four_tools(
    review_tools: dict[str, BaseTool],
) -> None:
    assert list(review_tools) == [
        "list_changed_files",
        "read_diff",
        "read_file",
        "search_code",
    ]


def test_list_changed_files_tool_formats_model_friendly_text(
    review_tools: dict[str, BaseTool],
) -> None:
    result = review_tools["list_changed_files"].invoke({})

    assert result == "[M] src/app.py\n[A] src/helper.py"


def test_read_diff_and_read_file_tools_use_bound_range(
    review_tools: dict[str, BaseTool],
) -> None:
    diff = review_tools["read_diff"].invoke({"path": "src/helper.py"})
    content = review_tools["read_file"].invoke({"path": "src/helper.py"})

    assert "diff --git a/src/helper.py b/src/helper.py" in diff
    assert "   1: def normalize(value):" in content


def test_search_code_tool_accepts_optional_path(
    review_tools: dict[str, BaseTool],
) -> None:
    found = review_tools["search_code"].invoke(
        {"query": "SELECT", "path": "src/app.py"}
    )
    missing = review_tools["search_code"].invoke(
        {"query": "SELECT", "path": "src/helper.py"}
    )

    assert "src/app.py:5:" in found
    assert missing == "没有找到匹配代码。"


def test_tool_rejects_path_traversal(review_tools: dict[str, BaseTool]) -> None:
    with pytest.raises(GitServiceError, match="仓库内"):
        review_tools["read_file"].invoke({"path": "../secret.txt"})
