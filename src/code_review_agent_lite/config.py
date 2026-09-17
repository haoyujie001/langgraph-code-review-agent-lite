"""从环境变量和 `.env` 加载应用配置。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API 与审查流程的共享配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CODE_REVIEW_",
        extra="ignore",
    )

    app_name: str = "LangGraph Code Review Agent Lite"
    app_version: str = "0.7.0"
    allowed_repo_root: Path = Field(default_factory=Path.cwd)
    git_timeout_seconds: int = Field(default=10, ge=1, le=60)
    max_file_chars: int = Field(default=20_000, ge=1_000, le=100_000)
    max_diff_chars: int = Field(default=50_000, ge=1_000, le=200_000)
    max_search_results: int = Field(default=20, ge=1, le=100)
    max_agent_rounds: int = Field(default=6, ge=1, le=10)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    llm_model: str = "deepseek-chat"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_timeout_seconds: int = Field(default=60, ge=5, le=180)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_structured_output_method: Literal[
        "json_schema",
        "function_calling",
        "json_mode",
    ] = "json_mode"
    output_dir: Path = Path("outputs")
    history_dir: Path = Path("outputs/history")


@lru_cache
def get_settings() -> Settings:
    """为当前进程创建并缓存配置。"""

    return Settings()
