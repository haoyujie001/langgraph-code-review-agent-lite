from code_review_agent_lite.reviewer import STRUCTURE_REVIEW_PROMPT


def test_json_mode_prompt_contains_every_required_finding_field() -> None:
    assert "JSON" in STRUCTURE_REVIEW_PROMPT
    for field in (
        "summary",
        "findings",
        "path",
        "line",
        "severity",
        "category",
        "message",
        "suggestion",
    ):
        assert f'"{field}"' in STRUCTURE_REVIEW_PROMPT
