"""Four read-only tools exposed to the LangGraph review agent."""

from langchain_core.tools import BaseTool, tool

from code_review_agent_lite.git_service import GitService


def build_review_tools(
    git_service: GitService,
    base_ref: str,
    head_ref: str,
) -> list[BaseTool]:
    """Bind one repository and commit range to four model-facing tools."""

    # Resolve the range once. The model never receives a repository path or chooses
    # a different commit after the review starts.
    base_sha, head_sha = git_service.resolve_range(base_ref, head_ref)

    @tool
    def list_changed_files() -> str:
        """列出本次审查范围内的变更文件及其 Git 状态。"""

        changed_files = git_service.list_changed_files(base_sha, head_sha)
        if not changed_files:
            return "本次提交范围没有文件变更。"
        return "\n".join(
            f"[{changed_file.status}] {changed_file.path}"
            for changed_file in changed_files
        )

    @tool
    def read_diff(path: str = "") -> str:
        """读取本次 Git Diff；传入相对路径时只读取该文件的 Diff。"""

        return git_service.read_diff(base_sha, head_sha, path=path or None)

    @tool
    def read_file(path: str) -> str:
        """读取 Head Commit 中一个仓库相对路径的文本文件，并显示行号。"""

        return git_service.read_file(path, head_sha)

    @tool
    def search_code(query: str, path: str = "") -> str:
        """在 Head Commit 的代码中搜索固定文本，可用相对路径限制范围。"""

        return git_service.search_code(query, head_sha, path=path or None)

    return [list_changed_files, read_diff, read_file, search_code]
