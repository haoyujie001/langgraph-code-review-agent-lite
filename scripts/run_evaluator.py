"""Run the real review workflow against a small synthetic dataset."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from code_review_agent_lite.config import get_settings
from code_review_agent_lite.evaluator import (
    CaseScore,
    EvaluationCase,
    load_dataset,
    score_case,
)
from code_review_agent_lite.git_service import GitServiceError
from code_review_agent_lite.history import HistoryStoreError
from code_review_agent_lite.reviewer import ModelInvocationError
from code_review_agent_lite.schemas import ReviewRequest
from code_review_agent_lite.service import ReviewService


def run_git(repo_path: Path, *arguments: str) -> str:
    """Run one deterministic Git command for a synthetic repository."""

    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Evaluator Git command failed: {detail}")
    return result.stdout.strip()


def create_case_repository(root: Path, case: EvaluationCase) -> tuple[Path, str, str]:
    """Create the before/after commits described by one dataset case."""

    repo_path = root / case.case_id
    repo_path.mkdir(parents=True)
    run_git(repo_path, "init", "--quiet", "--initial-branch=main")
    run_git(repo_path, "config", "user.name", "Code Review Evaluator")
    run_git(repo_path, "config", "user.email", "evaluator@example.invalid")
    run_git(repo_path, "config", "core.autocrlf", "false")

    write_snapshot(repo_path, case.files_before)
    run_git(repo_path, "add", "--all")
    run_git(repo_path, "commit", "--quiet", "-m", "before")
    base_sha = run_git(repo_path, "rev-parse", "HEAD")

    write_snapshot(repo_path, case.files_after)
    run_git(repo_path, "add", "--all")
    run_git(repo_path, "commit", "--quiet", "-m", "after")
    head_sha = run_git(repo_path, "rev-parse", "HEAD")
    return repo_path, base_sha, head_sha


def write_snapshot(repo_path: Path, files: dict[str, str]) -> None:
    """Write only safe repository-relative paths from the trusted dataset."""

    for relative_name, content in files.items():
        relative_path = PurePosixPath(relative_name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Evaluator path must stay in repository: {relative_name}")
        target = repo_path.joinpath(*relative_path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evals/cases.json"))
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument(
        "--case-id",
        action="append",
        help="只运行指定 case_id；可重复传入。",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    cases = load_dataset(args.dataset).cases
    if args.case_id:
        requested_ids = set(args.case_id)
        known_ids = {case.case_id for case in cases}
        unknown_ids = requested_ids - known_ids
        if unknown_ids:
            raise ValueError(f"Unknown case IDs: {sorted(unknown_ids)}")
        cases = [case for case in cases if case.case_id in requested_ids]
    if args.max_cases is not None:
        if args.max_cases < 1:
            raise ValueError("--max-cases must be at least 1")
        cases = cases[: args.max_cases]

    workspace_root = (settings.output_dir / "evaluator-workspaces").resolve()
    allowed_root = settings.allowed_repo_root.resolve()
    if not workspace_root.is_relative_to(allowed_root):
        raise RuntimeError("Evaluator workspace must be inside the allowed repo root.")
    workspace_root.mkdir(parents=True, exist_ok=True)

    service = ReviewService(settings)
    started_at = datetime.now(UTC)
    scores = []
    with TemporaryDirectory(prefix="run-", dir=workspace_root) as temporary_dir:
        run_root = Path(temporary_dir)
        for index, case in enumerate(cases, start=1):
            print(f"[{index}/{len(cases)}] {case.case_id}", flush=True)
            repo_path, base_sha, head_sha = create_case_repository(run_root, case)
            try:
                response = service.review(
                    ReviewRequest(
                        repo_path=repo_path,
                        base_ref=base_sha,
                        head_ref=head_sha,
                        review_focus=case.review_focus,
                        custom_rules=case.custom_rules,
                    )
                )
                score = score_case(case, response)
            except (GitServiceError, HistoryStoreError, ModelInvocationError) as exc:
                score = CaseScore(
                    case_id=case.case_id,
                    passed=False,
                    expected_count=len(case.expected_findings),
                    matched_count=0,
                    actual_count=0,
                    missing=case.expected_findings,
                    unexpected=[],
                    review_id="",
                    summary="",
                    error=f"{type(exc).__name__}: {exc}",
                )
            scores.append(score)
            outcome = "PASS" if score.passed else "FAIL"
            print(f"[{index}/{len(cases)}] {case.case_id}: {outcome}", flush=True)

    matched = sum(score.matched_count for score in scores)
    expected = sum(score.expected_count for score in scores)
    actual = sum(score.actual_count for score in scores)
    report = {
        "model": settings.llm_model,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "total_cases": len(scores),
        "passed_cases": sum(score.passed for score in scores),
        "failed_cases": sum(score.error is not None for score in scores),
        "precision": round(matched / actual, 4) if actual else 1.0,
        "recall": round(matched / expected, 4) if expected else 1.0,
        "cases": [score.model_dump(mode="json") for score in scores],
    }
    output_path = args.output or (
        settings.output_dir
        / "evaluations"
        / f"evaluation-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**report, "report_path": str(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
