"""Minimal dataset contracts and deterministic finding scorer."""

import json
from pathlib import Path

from pydantic import Field

from code_review_agent_lite.schemas import (
    Finding,
    FindingCategory,
    ReviewInstruction,
    ReviewResponse,
    Severity,
    StrictModel,
)


class ExpectedFinding(StrictModel):
    """The minimum evidence one evaluation case expects."""

    path: str
    category: FindingCategory
    line: int | None = Field(default=None, ge=1)
    severity: Severity | None = None


class EvaluationCase(StrictModel):
    """Two small repository snapshots and their expected findings."""

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,49}$")
    description: str
    files_before: dict[str, str]
    files_after: dict[str, str]
    review_focus: list[ReviewInstruction] = Field(default_factory=list, max_length=5)
    custom_rules: list[ReviewInstruction] = Field(default_factory=list, max_length=10)
    expected_findings: list[ExpectedFinding] = Field(default_factory=list)


class EvaluationDataset(StrictModel):
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)


class CaseScore(StrictModel):
    """Transparent per-case score used in the final JSON report."""

    case_id: str
    passed: bool
    expected_count: int
    matched_count: int
    actual_count: int
    missing: list[ExpectedFinding]
    unexpected: list[Finding]
    review_id: str
    summary: str
    error: str | None = None


def load_dataset(path: Path | str) -> EvaluationDataset:
    """Load and validate one UTF-8 JSON evaluator dataset."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return EvaluationDataset.model_validate(data)


def score_case(case: EvaluationCase, response: ReviewResponse) -> CaseScore:
    """Match expected findings one-to-one against actual structured findings."""

    unmatched_actual = list(response.findings)
    missing: list[ExpectedFinding] = []
    matched_count = 0

    for expected in case.expected_findings:
        match_index = next(
            (
                index
                for index, actual in enumerate(unmatched_actual)
                if finding_matches(expected, actual)
            ),
            None,
        )
        if match_index is None:
            missing.append(expected)
            continue
        matched_count += 1
        unmatched_actual.pop(match_index)

    # A clean case fails on any finding; issue cases expose extras but only fail
    # when an expected problem is missed.
    passed = not missing and (bool(case.expected_findings) or not unmatched_actual)
    return CaseScore(
        case_id=case.case_id,
        passed=passed,
        expected_count=len(case.expected_findings),
        matched_count=matched_count,
        actual_count=len(response.findings),
        missing=missing,
        unexpected=unmatched_actual,
        review_id=str(response.review_id),
        summary=response.summary,
    )


def finding_matches(expected: ExpectedFinding, actual: Finding) -> bool:
    """Use stable structural fields instead of brittle message text."""

    return (
        expected.path.replace("\\", "/") == actual.path.replace("\\", "/")
        and expected.category == actual.category
        and (expected.line is None or expected.line == actual.line)
        and (expected.severity is None or expected.severity == actual.severity)
    )
