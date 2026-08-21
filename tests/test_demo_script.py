from pathlib import Path

import pytest

from scripts.create_demo_repository import (
    DemoCreationError,
    create_demo_repository,
    run_git,
)


def test_create_demo_repository_builds_expected_commit_range(
    tmp_path: Path,
) -> None:
    repository = create_demo_repository(tmp_path / "demo")

    assert repository.path.is_dir()
    assert repository.base_sha != repository.head_sha
    assert run_git(repository.path, "rev-list", "--count", "HEAD") == "2"
    assert (
        run_git(
            repository.path,
            "diff",
            "--name-status",
            repository.base_sha,
            repository.head_sha,
        )
        == "M\tsrc/app.py\nA\tsrc/helper.py"
    )
    assert "SELECT * FROM users" in (repository.path / "src/app.py").read_text(
        encoding="utf-8"
    )


def test_create_demo_repository_refuses_non_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("do not replace", encoding="utf-8")

    with pytest.raises(DemoCreationError, match="must be empty"):
        create_demo_repository(target)

    assert (target / "keep.txt").read_text(encoding="utf-8") == "do not replace"
