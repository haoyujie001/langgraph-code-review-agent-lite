"""Strict HTTP and workflow data contracts."""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model that rejects misspelled or unexpected fields."""

    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class FindingCategory(StrEnum):
    security = "security"
    bug = "bug"
    performance = "performance"
    maintainability = "maintainability"


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    app_name: str
    version: str


class ReviewRequest(StrictModel):
    """Input contract for reviewing one Git commit range."""

    repo_path: Path
    base_ref: str = Field(default="HEAD~1", min_length=1, max_length=200)
    head_ref: str = Field(default="HEAD", min_length=1, max_length=200)


class Finding(StrictModel):
    """One structured problem returned by the review workflow."""

    path: str = Field(min_length=1, max_length=500)
    line: int = Field(ge=1)
    severity: Severity
    category: FindingCategory
    message: str = Field(min_length=1, max_length=2_000)
    suggestion: str = Field(min_length=1, max_length=2_000)


class ModelReviewResult(StrictModel):
    """Structured output produced after the Agent finishes using tools."""

    summary: str = Field(min_length=1, max_length=2_000)
    findings: list[Finding] = Field(default_factory=list, max_length=20)


class ReviewResponse(StrictModel):
    """Final review API response with a generated Markdown report path."""

    status: Literal["completed", "failed"]
    summary: str = Field(default="", max_length=2_000)
    findings: list[Finding] = Field(default_factory=list, max_length=10)
    markdown_report: Path | None = None
    error: str | None = Field(default=None, max_length=2_000)
