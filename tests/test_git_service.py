from pathlib import Path

import pytest
from conftest import DemoRepository

from code_review_agent_lite.git_service import GitService, GitServiceError
from scripts.create_demo_repository import run_git


def create_service(
    demo_repository: DemoRepository,
    allowed_root: Path,
    **limits: int,
) -> GitService:
    return GitService(
        repo_path=demo_repository.path,
        allowed_repo_root=allowed_root,
        **limits,
    )


def test_list_changed_files_reads_real_commit_range(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    service = create_service(demo_repository, tmp_path)

    changed_files = service.list_changed_files(
        demo_repository.base_sha,
        demo_repository.head_sha,
    )

    assert [(item.status, item.path) for item in changed_files] == [
        ("M", "src/app.py"),
        ("A", "src/helper.py"),
    ]


def test_read_diff_can_limit_output_to_one_file(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    service = create_service(demo_repository, tmp_path)

    diff = service.read_diff(
        demo_repository.base_sha,
        demo_repository.head_sha,
        path="src/app.py",
    )

    assert "diff --git a/src/app.py b/src/app.py" in diff
    assert "SELECT * FROM users" in diff
    assert "src/helper.py" not in diff


def test_read_file_uses_head_commit_and_adds_line_numbers(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    service = create_service(demo_repository, tmp_path)

    content = service.read_file("src/app.py", demo_repository.head_sha)

    assert "   1: def greet(name):" in content
    assert "   4: def build_query(user_id):" in content


def test_search_code_returns_bounded_commit_results(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    service = create_service(demo_repository, tmp_path)

    result = service.search_code("SELECT", demo_repository.head_sha)

    assert result.startswith("src/app.py:5:")
    assert "SELECT * FROM users" in result
    assert demo_repository.head_sha not in result


def test_repository_must_stay_under_allowed_root(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    unrelated_root = tmp_path / "allowed"
    unrelated_root.mkdir()

    with pytest.raises(GitServiceError, match="允许目录内"):
        create_service(demo_repository, unrelated_root)


@pytest.mark.parametrize(
    "path",
    ["../secret.txt", "D:/secret.txt", ".git/config", ""],
)
def test_file_path_must_be_repository_relative(
    demo_repository: DemoRepository,
    tmp_path: Path,
    path: str,
) -> None:
    service = create_service(demo_repository, tmp_path)

    with pytest.raises(GitServiceError, match="仓库内"):
        service.validate_relative_path(path)


def test_diff_output_is_truncated_at_configured_limit(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    service = create_service(demo_repository, tmp_path, max_diff_chars=120)

    diff, added_lines = service.read_diff_with_added_lines(
        demo_repository.base_sha,
        demo_repository.head_sha,
    )

    assert "[输出已截断，最多 120 个字符]" in diff
    assert 5 in added_lines["src/app.py"]


def test_sensitive_files_are_excluded_from_all_model_inputs(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    base_sha = demo_repository.head_sha
    app_file = demo_repository.path / "src" / "app.py"
    app_file.write_text(
        app_file.read_text(encoding="utf-8") + "\nSAFE_MARKER = True\n",
        encoding="utf-8",
    )
    (demo_repository.path / ".env").write_text(
        "TOP_SECRET=do-not-send\n",
        encoding="utf-8",
    )
    run_git(demo_repository.path, "add", "--all")
    run_git(demo_repository.path, "commit", "--quiet", "-m", "add configuration")
    head_sha = run_git(demo_repository.path, "rev-parse", "HEAD")
    service = create_service(demo_repository, tmp_path)

    changed_files = service.list_changed_files(base_sha, head_sha)
    diff = service.read_diff(base_sha, head_sha)

    assert [item.path for item in changed_files] == ["src/app.py"]
    assert "SAFE_MARKER" in diff
    assert "TOP_SECRET" not in diff
    assert ".env" not in diff
    assert service.search_code("TOP_SECRET", head_sha) == "没有找到匹配代码。"
    with pytest.raises(GitServiceError, match="敏感文件"):
        service.read_file(".env", head_sha)
