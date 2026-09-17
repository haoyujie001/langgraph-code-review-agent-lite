from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from code_review_agent_lite.evaluator import (
    EvaluationCase,
    ExpectedFinding,
    load_dataset,
    score_case,
)
from code_review_agent_lite.schemas import Finding, ReviewResponse
from scripts.run_evaluator import create_case_repository


def response_with(findings: list[Finding]) -> ReviewResponse:
    return ReviewResponse(
        review_id="11111111-1111-1111-1111-111111111111",
        status="completed",
        base_commit="a" * 40,
        head_commit="b" * 40,
        summary="审查完成。",
        findings=findings,
    )


def added_line_numbers(before: str, after: str) -> set[int]:
    """Return Head-snapshot lines introduced by insert or replace opcodes."""

    matcher = SequenceMatcher(a=before.splitlines(), b=after.splitlines())
    added: set[int] = set()
    for (
        tag,
        _before_start,
        _before_end,
        after_start,
        after_end,
    ) in matcher.get_opcodes():
        if tag in {"insert", "replace"}:
            added.update(range(after_start + 1, after_end + 1))
    return added


def test_evaluator_dataset_contains_fifty_balanced_cases() -> None:
    dataset_path = Path(__file__).parents[1] / "evals" / "cases.json"

    dataset = load_dataset(dataset_path)
    positive_cases = [case for case in dataset.cases if case.expected_findings]
    negative_cases = [case for case in dataset.cases if not case.expected_findings]
    categories = Counter(
        finding.category.value
        for case in positive_cases
        for finding in case.expected_findings
    )

    assert len(dataset.cases) == 50
    assert len({case.case_id for case in dataset.cases}) == 50
    assert len(positive_cases) == 38
    assert len(negative_cases) == 12
    assert categories == {
        "security": 12,
        "bug": 10,
        "performance": 8,
        "maintainability": 8,
    }
    assert any(case.custom_rules for case in dataset.cases)


def test_every_expected_finding_targets_an_added_line() -> None:
    dataset = load_dataset(Path(__file__).parents[1] / "evals" / "cases.json")

    for case in dataset.cases:
        for expected in case.expected_findings:
            assert expected.path in case.files_after, case.case_id
            added_lines = added_line_numbers(
                case.files_before.get(expected.path, ""),
                case.files_after[expected.path],
            )
            assert expected.line in added_lines, case.case_id


def test_score_case_matches_structural_fields() -> None:
    case = EvaluationCase(
        case_id="sql_case",
        description="SQL injection",
        files_before={"app.py": "safe = True\n"},
        files_after={"app.py": "query = user_input\n"},
        expected_findings=[ExpectedFinding(path="app.py", line=1, category="security")],
    )
    finding = Finding(
        path="app.py",
        line=1,
        severity="high",
        category="security",
        message="SQL 注入。",
        suggestion="参数化查询。",
    )

    score = score_case(case, response_with([finding]))

    assert score.passed is True
    assert score.matched_count == 1
    assert score.unexpected == []


def test_clean_case_fails_when_model_reports_false_positive() -> None:
    case = EvaluationCase(
        case_id="clean_case",
        description="Safe change",
        files_before={"app.py": "value = 1\n"},
        files_after={"app.py": "value = 2\n"},
    )
    false_positive = Finding(
        path="app.py",
        line=1,
        severity="low",
        category="maintainability",
        message="不必要的问题。",
        suggestion="无需修改。",
    )

    score = score_case(case, response_with([false_positive]))

    assert score.passed is False
    assert score.unexpected == [false_positive]


def test_all_evaluator_cases_create_real_commit_ranges(tmp_path: Path) -> None:
    dataset = load_dataset(Path(__file__).parents[1] / "evals" / "cases.json")

    for case in dataset.cases:
        repo_path, base_sha, head_sha = create_case_repository(tmp_path, case)

        assert repo_path.is_dir(), case.case_id
        assert len(base_sha) == 40, case.case_id
        assert len(head_sha) == 40, case.case_id
        assert base_sha != head_sha, case.case_id
