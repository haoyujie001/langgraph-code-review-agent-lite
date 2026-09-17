"""FastAPI 与离线评测器共享的应用服务。"""

from uuid import UUID

from code_review_agent_lite.config import Settings
from code_review_agent_lite.git_service import GitService
from code_review_agent_lite.graph import build_review_graph
from code_review_agent_lite.history import HistoryStore
from code_review_agent_lite.reviewer import ToolCallingModel, create_chat_model
from code_review_agent_lite.schemas import (
    ReviewHistoryList,
    ReviewHistoryRecord,
    ReviewRequest,
    ReviewResponse,
)
from code_review_agent_lite.state import create_initial_state
from code_review_agent_lite.tools import build_review_tools


class ReviewService:
    """执行审查并提供本地历史记录。"""

    def __init__(
        self,
        settings: Settings,
        model: ToolCallingModel | None = None,
    ) -> None:
        self.settings = settings
        self.model = model
        self.history_store = HistoryStore(settings.history_dir)

    def review(self, request: ReviewRequest) -> ReviewResponse:
        """构建请求级工具并调用 LangGraph 工作流。"""

        git_service = GitService(
            repo_path=request.repo_path,
            allowed_repo_root=self.settings.allowed_repo_root,
            timeout_seconds=self.settings.git_timeout_seconds,
            max_file_chars=self.settings.max_file_chars,
            max_diff_chars=self.settings.max_diff_chars,
            max_search_results=self.settings.max_search_results,
        )
        tools = build_review_tools(
            git_service,
            request.base_ref,
            request.head_ref,
        )
        review_graph = build_review_graph(
            git_service,
            tools,
            self.model or create_chat_model(self.settings),
            max_agent_rounds=self.settings.max_agent_rounds,
            max_tool_calls=self.settings.max_tool_calls,
            structured_output_method=self.settings.llm_structured_output_method,
            output_dir=self.settings.output_dir,
            history_store=self.history_store,
        )
        result = review_graph.invoke(create_initial_state(request))
        return ReviewResponse(
            review_id=result["review_id"],
            status=result["status"],
            base_commit=result["base_commit"],
            head_commit=result["head_commit"],
            summary=result["summary"],
            findings=result["findings"],
            markdown_report=result["markdown_report"],
            error=result["error"],
        )

    def list_history(self, *, limit: int) -> ReviewHistoryList:
        return self.history_store.list(limit=limit)

    def get_history(self, review_id: UUID) -> ReviewHistoryRecord:
        return self.history_store.get(review_id)
