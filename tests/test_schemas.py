import pytest
from pydantic import ValidationError

from code_review_agent_lite.schemas import Finding, ReviewRequest, ReviewResponse


def test_review_request_uses_small_commit_range_defaults() -> None:
    request = ReviewRequest(repo_path="D:/agent/demo")

    assert request.base_ref == "HEAD~1"
    assert request.head_ref == "HEAD"


def test_finding_parses_enum_values() -> None:
    finding = Finding(
        path="src/user.py",
        line=12,
        severity="high",
        category="security",
        message="SQL 查询使用了字符串拼接。",
        suggestion="改用参数化查询。",
    )

    response = ReviewResponse(
        status="completed",
        summary="发现一个问题。",
        findings=[finding],
    )

    assert response.findings[0].severity.value == "high"
    assert response.findings[0].category.value == "security"


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ReviewRequest(
            repo_path="D:/agent/demo",
            base="main",
        )


def test_finding_rejects_invalid_line_and_severity() -> None:
    with pytest.raises(ValidationError):
        Finding(
            path="src/user.py",
            line=0,
            severity="urgent",
            category="security",
            message="问题描述。",
            suggestion="修复建议。",
        )
