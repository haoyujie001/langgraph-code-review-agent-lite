"""FastAPI application entry point."""

from fastapi import FastAPI, HTTPException

from code_review_agent_lite.config import Settings, get_settings
from code_review_agent_lite.git_service import GitService, GitServiceError
from code_review_agent_lite.graph import build_review_graph
from code_review_agent_lite.reviewer import (
    ModelConfigurationError,
    ModelInvocationError,
    ToolCallingModel,
    create_chat_model,
)
from code_review_agent_lite.schemas import (
    HealthResponse,
    ReviewRequest,
    ReviewResponse,
)
from code_review_agent_lite.state import create_initial_state
from code_review_agent_lite.tools import build_review_tools


def create_app(
    settings: Settings | None = None,
    model: ToolCallingModel | None = None,
) -> FastAPI:
    """Create an application with explicit, testable settings."""

    app_settings = settings or get_settings()
    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description="A small Code Review Agent built while learning LangGraph.",
    )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            app_name=app_settings.app_name,
            version=app_settings.app_version,
        )

    @application.post("/reviews", response_model=ReviewResponse, tags=["reviews"])
    def review(request: ReviewRequest) -> ReviewResponse:
        try:
            git_service = GitService(
                repo_path=request.repo_path,
                allowed_repo_root=app_settings.allowed_repo_root,
                timeout_seconds=app_settings.git_timeout_seconds,
                max_file_chars=app_settings.max_file_chars,
                max_diff_chars=app_settings.max_diff_chars,
                max_search_results=app_settings.max_search_results,
            )
            tools = build_review_tools(
                git_service,
                request.base_ref,
                request.head_ref,
            )
            review_graph = build_review_graph(
                git_service,
                tools,
                model or create_chat_model(app_settings),
                max_agent_rounds=app_settings.max_agent_rounds,
                max_tool_calls=app_settings.max_tool_calls,
                structured_output_method=(app_settings.llm_structured_output_method),
                output_dir=app_settings.output_dir,
            )
            result = review_graph.invoke(create_initial_state(request))
        except GitServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ModelConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ModelInvocationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return ReviewResponse(
            status=result["status"],
            summary=result["summary"],
            findings=result["findings"],
            markdown_report=result["markdown_report"],
            error=result["error"],
        )

    return application


app = create_app()
