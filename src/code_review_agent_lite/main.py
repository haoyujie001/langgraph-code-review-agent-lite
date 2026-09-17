"""FastAPI 应用入口。"""

from uuid import UUID

from fastapi import FastAPI, HTTPException, Query

from code_review_agent_lite.config import Settings, get_settings
from code_review_agent_lite.git_service import GitServiceError
from code_review_agent_lite.history import HistoryNotFoundError, HistoryStoreError
from code_review_agent_lite.reviewer import (
    ModelConfigurationError,
    ModelInvocationError,
    ToolCallingModel,
)
from code_review_agent_lite.schemas import (
    HealthResponse,
    ReviewHistoryList,
    ReviewHistoryRecord,
    ReviewRequest,
    ReviewResponse,
)
from code_review_agent_lite.service import ReviewService


def create_app(
    settings: Settings | None = None,
    model: ToolCallingModel | None = None,
) -> FastAPI:
    """使用显式、可测试的配置创建应用。"""

    app_settings = settings or get_settings()
    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description="A small Code Review Agent built while learning LangGraph.",
    )
    review_service = ReviewService(app_settings, model)

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            app_name=app_settings.app_name,
            version=app_settings.app_version,
        )

    @application.post("/reviews", response_model=ReviewResponse, tags=["reviews"])
    def review(request: ReviewRequest) -> ReviewResponse:
        try:
            return review_service.review(request)
        except GitServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ModelConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ModelInvocationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except HistoryStoreError as exc:
            raise HTTPException(status_code=500, detail="审查历史保存失败。") from exc

    @application.get(
        "/reviews",
        response_model=ReviewHistoryList,
        tags=["reviews"],
    )
    def list_reviews(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> ReviewHistoryList:
        return review_service.list_history(limit=limit)

    @application.get(
        "/reviews/{review_id}",
        response_model=ReviewHistoryRecord,
        tags=["reviews"],
    )
    def get_review(review_id: UUID) -> ReviewHistoryRecord:
        try:
            return review_service.get_history(review_id)
        except HistoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return application


app = create_app()
