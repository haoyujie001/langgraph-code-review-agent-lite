from pathlib import Path

import pytest

from code_review_agent_lite.git_service import ChangedFile
from code_review_agent_lite.history import HistoryNotFoundError, HistoryStore
from code_review_agent_lite.schemas import ReviewRequest
from code_review_agent_lite.state import create_initial_state


def completed_state(tmp_path: Path):
    state = create_initial_state(
        ReviewRequest(
            repo_path=tmp_path,
            base_ref="main",
            head_ref="feature",
            review_focus=["安全性"],
            custom_rules=["禁止拼接 SQL"],
        )
    )
    state.update(
        base_commit="a" * 40,
        head_commit="b" * 40,
        changed_files=[ChangedFile(status="M", path="src/app.py")],
        status="completed",
        summary="发现一处问题。",
        markdown_report=tmp_path / "review.md",
    )
    return state


def test_history_store_round_trips_final_state(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history")
    state = completed_state(tmp_path)

    saved = store.save_state(state)
    loaded = store.get(saved.review_id)
    history = store.list(limit=20)

    assert loaded.review_id == saved.review_id
    assert loaded.custom_rules == ["禁止拼接 SQL"]
    assert loaded.changed_files == ["src/app.py"]
    assert history.total == 1
    assert history.items[0].review_id == saved.review_id


def test_history_store_reports_missing_review(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history")

    with pytest.raises(HistoryNotFoundError, match="未找到审查记录"):
        store.get("11111111-1111-1111-1111-111111111111")
