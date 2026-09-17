import asyncio
from pathlib import Path

import pytest
from conftest import DemoRepository, ScriptedToolCallingModel
from httpx import ASGITransport, AsyncClient, Response
from langchain_core.messages import AIMessage

from code_review_agent_lite.config import Settings
from code_review_agent_lite.main import create_app
from code_review_agent_lite.schemas import Finding, ModelReviewResult


class WrongReviewTypeModel(ScriptedToolCallingModel):
    """返回无效模型值但不主动抛出异常。"""

    def invoke(self, messages):
        self.received_messages.append(list(messages))
        return "not-an-ai-message"


def post_json(app, path: str, payload: dict[str, object]) -> Response:
    """向 FastAPI 应用发送进程内 POST 请求。"""

    async def request() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(path, json=payload)

    return asyncio.run(request())


def get_json(app, path: str) -> Response:
    """向 FastAPI 应用发送进程内 GET 请求。"""

    async def request() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def review_payload(demo_repository: DemoRepository) -> dict[str, object]:
    return {
        "repo_path": str(demo_repository.path),
        "base_ref": demo_repository.base_sha,
        "head_ref": demo_repository.head_sha,
    }


def test_review_endpoint_invokes_agent_graph(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    model = ScriptedToolCallingModel(
        [AIMessage(content="代码审查完成，建议修复 SQL 字符串拼接。")],
        ModelReviewResult(
            summary="发现一处 SQL 注入问题。",
            findings=[
                Finding(
                    path="src/app.py",
                    line=5,
                    severity="high",
                    category="security",
                    message="SQL 查询使用了字符串拼接。",
                    suggestion="改用参数化查询。",
                )
            ],
        ),
    )
    app = create_app(
        Settings(
            allowed_repo_root=tmp_path,
            output_dir=tmp_path / "reports",
            history_dir=tmp_path / "history",
            _env_file=None,
        ),
        model=model,
    )

    response = post_json(app, "/reviews", review_payload(demo_repository))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["base_commit"] == demo_repository.base_sha
    assert body["head_commit"] == demo_repository.head_sha
    assert body["summary"] == "发现一处 SQL 注入问题。"
    assert body["findings"][0]["path"] == "src/app.py"
    report_path = Path(body["markdown_report"])
    assert report_path.is_file()
    assert "SQL 查询使用了字符串拼接" in report_path.read_text(encoding="utf-8")
    assert body["error"] is None

    history = get_json(app, "/reviews").json()
    assert history["total"] == 1
    assert history["items"][0]["review_id"] == body["review_id"]
    detail = get_json(app, f"/reviews/{body['review_id']}")
    assert detail.status_code == 200
    assert detail.json()["summary"] == body["summary"]


def test_review_endpoint_maps_repository_errors_to_bad_request(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(allowed_repo_root=tmp_path, _env_file=None),
        model=ScriptedToolCallingModel([]),
    )

    response = post_json(
        app,
        "/reviews",
        {"repo_path": str(tmp_path / "missing")},
    )

    assert response.status_code == 400
    assert "仓库目录不存在" in response.json()["detail"]


def test_review_endpoint_requires_model_configuration(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    app = create_app(Settings(allowed_repo_root=tmp_path, _env_file=None))

    response = post_json(app, "/reviews", review_payload(demo_repository))

    assert response.status_code == 503
    assert "CODE_REVIEW_LLM_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize("failure_phase", ["review", "structured"])
def test_review_endpoint_maps_model_failures_to_bad_gateway(
    demo_repository: DemoRepository,
    tmp_path: Path,
    failure_phase: str,
) -> None:
    model = ScriptedToolCallingModel(
        [AIMessage(content="审查完成。")],
        review_error=(
            TimeoutError("simulated provider timeout")
            if failure_phase == "review"
            else None
        ),
        structured_error=(
            ValueError("simulated invalid structured output")
            if failure_phase == "structured"
            else None
        ),
    )
    app = create_app(
        Settings(
            allowed_repo_root=tmp_path,
            output_dir=tmp_path / "reports",
            history_dir=tmp_path / "history",
            _env_file=None,
        ),
        model=model,
    )

    response = post_json(app, "/reviews", review_payload(demo_repository))

    assert response.status_code == 502
    assert "失败" in response.json()["detail"]
    assert "simulated" not in response.json()["detail"]


def test_review_endpoint_maps_wrong_model_types_to_bad_gateway(
    demo_repository: DemoRepository,
    tmp_path: Path,
) -> None:
    wrong_review_model = WrongReviewTypeModel([])
    wrong_structured_model = ScriptedToolCallingModel([AIMessage(content="审查完成。")])
    wrong_structured_model.structured_result = {"summary": "invalid"}

    for model in (wrong_review_model, wrong_structured_model):
        app = create_app(
            Settings(
                allowed_repo_root=tmp_path,
                output_dir=tmp_path / "reports",
                history_dir=tmp_path / "history",
                _env_file=None,
            ),
            model=model,
        )
        response = post_json(app, "/reviews", review_payload(demo_repository))

        assert response.status_code == 502
        assert "失败" in response.json()["detail"]
