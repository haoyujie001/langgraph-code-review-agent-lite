"""在严格限制仓库、提交、路径、敏感文件、执行时间和输出长度的前提下，为上层提供只读 Git 数据"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@") #@@ -3,2 +3,3 @@
SENSITIVE_FILENAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
    "secrets.toml",
    "secrets.yaml",
    "secrets.yml",
}
SENSITIVE_SUFFIXES = {".jks", ".key", ".keystore", ".p12", ".pem", ".pfx"}
SAFE_ENV_TEMPLATES = {".env.example", ".env.sample", ".env.template"}


def is_sensitive_path(path: str) -> bool:
    """判断仓库路径是否可能包含凭据。"""

    name = PurePosixPath(path.replace("\\", "/")).name.casefold()
    if name in SAFE_ENV_TEMPLATES:
        return False
    return (
        name.startswith(".env")
        or name in SENSITIVE_FILENAMES
        or any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)
    )


def extract_added_lines(diff: str) -> dict[str, set[int]]:
    """提取统一 Diff 中各文件的新增行号。"""

    added_lines: dict[str, set[int]] = {}
    current_path: str | None = None
    next_head_line: int | None = None

    for line in diff.splitlines():
        if line.startswith("diff --git "): #遇到新文件时重置状态
            current_path = None
            next_head_line = None
            continue
        if next_head_line is None and line.startswith("+++ "): #--- 表示旧文件，+++ 表示新文件
            header_path = line[4:]
            current_path = (
                header_path.removeprefix("b/") if header_path != "/dev/null" else None
            )
            continue
# --- a/src/app.py
# +++ b/src/app.py
        hunk_match = HUNK_HEADER_PATTERN.match(line)
        if hunk_match:
            next_head_line = int(hunk_match.group("start"))
            continue
        if current_path is None or next_head_line is None:
            continue
        if line.startswith("+"):
            added_lines.setdefault(current_path, set()).add(next_head_line)
            next_head_line += 1
        elif line.startswith("-") or line.startswith("\\"):
            continue
        elif line.startswith(" "):
            next_head_line += 1

    return added_lines


class GitServiceError(RuntimeError):
    """仓库校验或只读 Git 命令失败时抛出。"""


@dataclass(frozen=True)
class ChangedFile:
    """`git diff --name-status` 返回的单个文件。"""

    status: str
    path: str


class GitService:
    """读取已校验本地仓库中的有界提交范围。"""

    def __init__(
        self,
        repo_path: Path | str,
        allowed_repo_root: Path | str,
        *,
        timeout_seconds: int = 10,
        max_file_chars: int = 20_000,
        max_diff_chars: int = 50_000,
        max_search_results: int = 20,
    ) -> None:
        self.allowed_repo_root = Path(allowed_repo_root).resolve()
        self.repo_path = Path(repo_path).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_file_chars = max_file_chars
        self.max_diff_chars = max_diff_chars
        self.max_search_results = max_search_results
        self._validate_repository()

    def resolve_commit(self, ref: str) -> str:
        """将 revision 解析为完整 commit SHA。"""

        cleaned_ref = ref.strip()
        if not cleaned_ref or len(cleaned_ref) > 200 or cleaned_ref.startswith("-"):
            raise GitServiceError(f"无效的 Git revision: {ref!r}")

        output = self._run_git(
            ["rev-parse", "--verify", f"{cleaned_ref}^{{commit}}"],
            output_limit=100,
        )
        return output.strip()

    def list_changed_files(
        self,
        base_ref: str,
        head_ref: str,
    ) -> list[ChangedFile]:
        """返回两个提交之间的文件状态与路径。"""

        base_sha, head_sha = self.resolve_range(base_ref, head_ref)
        changed_files = self._list_changed_files(base_sha, head_sha)
        return [item for item in changed_files if not is_sensitive_path(item.path)]

    def _list_changed_files(  #git diff --name-status base head
        self,
        base_sha: str,
        head_sha: str,
    ) -> list[ChangedFile]:
        """返回两个已解析提交间的未过滤文件列表。"""

        output = self._run_git_raw(
            [
                "-c",
                "core.quotepath=false",
                "diff",
                "--name-status",
                "--no-renames",
                base_sha,
                head_sha,
                "--",
            ],
        )

        changed_files: list[ChangedFile] = []
        for line in output.splitlines():
            status, separator, path = line.partition("\t")
            if separator and path:
                changed_files.append(ChangedFile(status=status, path=path))
        return changed_files

    def read_diff(
        self,
        base_ref: str,
        head_ref: str,
        path: str | None = None,
    ) -> str:
        """返回整个范围或单个文件的有界统一 Diff。"""

        diff, _added_lines = self.read_diff_with_added_lines(
            base_ref,
            head_ref,
            path=path,
        )
        return diff

    def read_diff_with_added_lines(  #git diff -U3 <base_sha> <head_sha> -- <文件路径>
        self,
        base_ref: str,
        head_ref: str,
        path: str | None = None,
    ) -> tuple[str, dict[str, set[int]]]:
        """返回有界 Diff 文本及完整新增行元数据。"""

        base_sha, head_sha = self.resolve_range(base_ref, head_ref)
        if path:
            review_paths = [self.validate_review_path(path)]
        else:
            review_paths = [
                item.path
                for item in self._list_changed_files(base_sha, head_sha)
                if not is_sensitive_path(item.path)
            ]
        if not review_paths:
            return "本次提交范围没有可审查的非敏感差异。", {}

        command = [
            "-c",
            "core.quotepath=false",
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--no-renames",
            "--unified=3",
            base_sha,
            head_sha,
            "--",
            *review_paths,
        ]
        complete_output = self._run_git_raw(command)
        if not complete_output:
            return "本次提交范围没有差异。", {}
        return (
            self._limit_text(complete_output, self.max_diff_chars),
            extract_added_lines(complete_output),
        )

    def read_file(self, path: str, ref: str) -> str: #git show <commit_sha>:<文件路径>
        """读取提交中的文本文件并添加行号。"""

        relative_path = self.validate_review_path(path)
        commit_sha = self.resolve_commit(ref)
        output = self._run_git(
            ["show", f"{commit_sha}:{relative_path}"],
            output_limit=self.max_file_chars,
        )
        if "\x00" in output:
            raise GitServiceError(f"不支持读取二进制文件: {relative_path}")
        if not output:
            return "（空文件）"

        return "\n".join(
            f"{line_number:4}: {line}"
            for line_number, line in enumerate(output.splitlines(), start=1) #使用 enumerate() 生成行号
        ) #从1开始为每一行编号。

    def search_code(  #git grep -n "<搜索内容>" <commit>
        self,
        query: str,
        ref: str,
        path: str | None = None,
    ) -> str:
        """在提交的跟踪文件中搜索固定文本。"""

        cleaned_query = query.strip()
        if not cleaned_query or len(cleaned_query) > 200 or "\x00" in cleaned_query:
            raise GitServiceError("搜索词长度必须在 1 到 200 个字符之间。")

        commit_sha = self.resolve_commit(ref)
        command = [
            "-c",
            "core.quotepath=false",
            "grep",
            "-n",
            "-I",
            "-F",
            "-e",
            cleaned_query,
            commit_sha,
            "--",
        ]
        if path:
            command.append(self.validate_review_path(path))

        output = self._run_git(
            command,
            allowed_return_codes={0, 1},
            output_limit=self.max_diff_chars,
        )
        if not output:
            return "没有找到匹配代码。"

        # `git grep <commit>` 会添加 `<sha>:` 前缀，此处移除固定 SHA。
        prefix = f"{commit_sha}:"
        matches = [
            line.removeprefix(prefix) for line in output.splitlines() if line.strip()
        ]
        matches = [
            line for line in matches if not is_sensitive_path(line.split(":", 1)[0])
        ]
        if not matches:
            return "没有找到匹配代码。"
        visible_matches = matches[: self.max_search_results]
        if len(matches) > self.max_search_results:
            visible_matches.append(
                f"[结果已截断，最多显示 {self.max_search_results} 条]"
            )
        return "\n".join(visible_matches)

    def resolve_range(self, base_ref: str, head_ref: str) -> tuple[str, str]:
        """在构造 Diff 命令前解析两个端点。"""

        return self.resolve_commit(base_ref), self.resolve_commit(head_ref)

    def validate_relative_path(self, path: str) -> str:
        """规范化路径并确保它位于所选仓库内。"""

        normalized = path.strip().replace("\\", "/")
        posix_path = PurePosixPath(normalized)
        windows_path = PureWindowsPath(path)
        if (
            not normalized
            or normalized == "."
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in posix_path.parts
            or ".git" in {part.casefold() for part in posix_path.parts}
        ):
            raise GitServiceError(f"文件路径必须位于仓库内: {path!r}")

        # 解析候选路径也能发现指向仓库外的符号链接。
        candidate = (self.repo_path / Path(*posix_path.parts)).resolve()
        if not candidate.is_relative_to(self.repo_path):
            raise GitServiceError(f"文件路径超出仓库范围: {path!r}")
        return posix_path.as_posix()

    def validate_review_path(self, path: str) -> str:
        """校验模型路径并拒绝常见凭据文件。"""

        relative_path = self.validate_relative_path(path)
        if is_sensitive_path(relative_path):
            raise GitServiceError(f"禁止审查敏感文件: {relative_path}")
        return relative_path

    def _validate_repository(self) -> None:
        if not self.allowed_repo_root.is_dir():
            raise GitServiceError(f"允许目录不存在: {self.allowed_repo_root}")
        if not self.repo_path.is_dir():
            raise GitServiceError(f"仓库目录不存在: {self.repo_path}")
        if not self.repo_path.is_relative_to(self.allowed_repo_root):
            raise GitServiceError(f"仓库必须位于允许目录内: {self.allowed_repo_root}")

        top_level = self._run_git(
            ["rev-parse", "--show-toplevel"],
            output_limit=1_000,
        )
        if Path(top_level).resolve() != self.repo_path:
            raise GitServiceError("repo_path 必须直接指向 Git 仓库根目录。")

    def _run_git(
        self,
        arguments: Iterable[str],
        *,
        output_limit: int,
        allowed_return_codes: set[int] | None = None,
    ) -> str:
        """不经 shell 执行 Git 并返回有界标准输出。"""

        output = self._run_git_raw(
            arguments,
            allowed_return_codes=allowed_return_codes,
        )
        return self._limit_text(output, output_limit)

    def _run_git_raw(#使用 ["git", *arguments] 将 Git 程序和命令参数组合起来，再交给 subprocess.run() 执行。
        self,
        arguments: Iterable[str],
        *,
        allowed_return_codes: set[int] | None = None,
    ) -> str:
        """不截断标准输出地执行 Git，供调用方提取元数据。"""

        return_codes = allowed_return_codes or {0}
        environment = os.environ.copy()
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        environment["GIT_LITERAL_PATHSPECS"] = "1"
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise GitServiceError("未找到 Git 命令，请先安装 Git。") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitServiceError(
                f"Git 命令执行超过 {self.timeout_seconds} 秒。"
            ) from exc

        if result.returncode not in return_codes:
            detail = result.stderr.strip() or result.stdout.strip() or "未知错误"
            raise GitServiceError(f"Git 命令执行失败: {detail}")
        return result.stdout.rstrip()

    @staticmethod
    def _limit_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}\n\n[输出已截断，最多 {limit} 个字符]"
