"""Create a two-commit Git repository for the final project demo."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


class DemoCreationError(RuntimeError):
    """Raised when the demo repository cannot be created safely."""


@dataclass(frozen=True)
class DemoRepository:
    """Repository path and the commit range consumed by `/reviews`."""

    path: Path
    base_sha: str
    head_sha: str


def run_git(repo_path: Path, *arguments: str) -> str:
    """Run one bounded Git command and return its standard output."""

    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=True,
        )
    except FileNotFoundError as exc:
        raise DemoCreationError("Git is not installed or is not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise DemoCreationError("Git command timed out after 10 seconds.") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "unknown Git error"
        raise DemoCreationError(detail) from exc
    return result.stdout.strip()


def create_demo_repository(target: Path) -> DemoRepository:
    """Create a base commit and a head commit containing one review issue."""

    target = target.expanduser().resolve()
    if target.exists() and not target.is_dir():
        raise DemoCreationError(f"Target is not a directory: {target}")
    if target.exists() and any(target.iterdir()):
        raise DemoCreationError(
            f"Target directory must be empty to avoid overwriting files: {target}"
        )

    target.mkdir(parents=True, exist_ok=True)
    run_git(target, "init", "--quiet")
    run_git(target, "config", "user.name", "Agent Demo")
    run_git(target, "config", "user.email", "agent-demo@example.com")

    source_dir = target / "src"
    source_dir.mkdir()
    app_file = source_dir / "app.py"
    app_file.write_text(
        'def greet(name):\n    return f"Hello, {name}"\n',
        encoding="utf-8",
    )
    run_git(target, "add", "--all")
    run_git(target, "commit", "--quiet", "-m", "add safe user query")
    base_sha = run_git(target, "rev-parse", "HEAD")

    # The second commit is intentionally unsafe so the review has a clear target.
    app_file.write_text(
        "def greet(name):\n"
        '    return f"Hello, {name}!"\n\n'
        "def build_query(user_id):\n"
        '    return f"SELECT * FROM users WHERE id = {user_id}"\n',
        encoding="utf-8",
    )
    (source_dir / "helper.py").write_text(
        "def normalize(value):\n    return value.strip().lower()\n",
        encoding="utf-8",
    )
    run_git(target, "add", "--all")
    run_git(target, "commit", "--quiet", "-m", "change user query")
    head_sha = run_git(target, "rev-parse", "HEAD")

    return DemoRepository(path=target, base_sha=base_sha, head_sha=head_sha)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the two-commit repository used by the Agent demo."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("outputs/demo-repository"),
        help="Empty target directory (default: outputs/demo-repository).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        repository = create_demo_repository(args.target)
    except DemoCreationError as exc:
        print(f"Failed to create demo repository: {exc}", file=sys.stderr)
        return 1

    payload = asdict(repository)
    payload["path"] = str(repository.path)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
