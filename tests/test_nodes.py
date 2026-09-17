from pathlib import Path

from code_review_agent_lite.git_service import ChangedFile, extract_added_lines
from code_review_agent_lite.nodes import (
    MAX_FINDINGS,
    generate_report,
    validate_findings,
)
from code_review_agent_lite.schemas import Finding


def make_finding(path: str, line: int, message: str) -> Finding:
    return Finding(
        path=path,
        line=line,
        severity="medium",
        category="bug",
        message=message,
        suggestion="修复这个问题。",
    )


def test_validate_findings_filters_paths_deduplicates_and_limits() -> None:
    duplicate = make_finding("./src/app.py", 5, "重复问题")
    candidates = [
        make_finding("src/not-changed.py", 1, "幻觉路径"),
        make_finding("src/app.py", 999_999, "幻觉行号"),
        duplicate,
        duplicate.model_copy(),
        *[make_finding("src/app.py", line, f"问题 {line}") for line in range(10, 22)],
    ]

    accepted = validate_findings(
        candidates,
        [ChangedFile(status="M", path="src/app.py")],
        extract_added_lines(
            "\n".join(
                [
                    "diff --git a/src/app.py b/src/app.py",
                    "--- /dev/null",
                    "+++ b/src/app.py",
                    "@@ -0,0 +1,30 @@",
                    *[f"+line {line}" for line in range(1, 31)],
                ]
            )
        ),
    )

    assert len(accepted) == MAX_FINDINGS
    assert accepted[0].path == "src/app.py"
    assert accepted[0].message == "重复问题"
    assert all(finding.path == "src/app.py" for finding in accepted)
    assert sum(finding.message == "重复问题" for finding in accepted) == 1
    assert all(finding.line != 999_999 for finding in accepted)


def test_validate_findings_keeps_only_added_diff_lines() -> None:
    diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -3,2 +3,3 @@
 context line
+added line
 another context line
"""

    assert extract_added_lines(diff) == {"src/app.py": {4}}

    accepted = validate_findings(
        [
            make_finding("src/app.py", 3, "上下文行"),
            make_finding("src/app.py", 4, "新增行"),
            make_finding("src/app.py", 99, "越界行"),
        ],
        [ChangedFile(status="M", path="src/app.py")],
        extract_added_lines(diff),
    )

    assert [finding.line for finding in accepted] == [4]


def test_generate_report_uses_unique_paths(tmp_path: Path) -> None:
    state = {
        "review_id": "11111111111111111111111111111111",
        "base_commit": "a" * 40,
        "head_commit": "b" * 40,
        "changed_files": [],
        "review_focus": [],
        "custom_rules": [],
        "summary": "审查完成。",
        "findings": [],
        "error": None,
    }

    first = generate_report(state, output_dir=tmp_path)["markdown_report"]
    state["review_id"] = "22222222222222222222222222222222"
    second = generate_report(state, output_dir=tmp_path)["markdown_report"]

    assert first != second
    assert first.is_file()
    assert second.is_file()
