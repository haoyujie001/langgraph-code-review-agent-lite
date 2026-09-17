import asyncio

from httpx import ASGITransport, AsyncClient, Response

from code_review_agent_lite.config import Settings
from code_review_agent_lite.main import create_app


def get(app, path: str) -> Response:
    """不启动服务器，发送进程内 HTTP 请求。"""

    async def request() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_health_returns_injected_application_metadata() -> None:
    app = create_app(
        Settings(
            app_name="Review Agent Test",
            app_version="9.9.9",
            allowed_repo_root="D:/agent",
            _env_file=None,
        )
    )

    response = get(app, "/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_name": "Review Agent Test",
        "version": "9.9.9",
    }


def test_openapi_contains_health_and_review_endpoints() -> None:
    app = create_app(Settings(_env_file=None))

    paths = get(app, "/openapi.json").json()["paths"]

    assert "/health" in paths
    assert "/reviews" in paths
