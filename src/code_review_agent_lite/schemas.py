"""严格的 HTTP 与工作流数据契约。"""

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class StrictModel(BaseModel):
    """拒绝未知字段的基础模型。"""

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


ReviewInstruction = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class ReviewRequest(StrictModel):
    """Git 提交范围的审查请求。"""

    repo_path: Path
    base_ref: str = Field(default="HEAD~1", min_length=1, max_length=200)
    head_ref: str = Field(default="HEAD", min_length=1, max_length=200)
    review_focus: list[ReviewInstruction] = Field(default_factory=list, max_length=5)
    custom_rules: list[ReviewInstruction] = Field(default_factory=list, max_length=10)

    @field_validator("review_focus", "custom_rules")
    @classmethod
    def remove_duplicate_instructions(cls, values: list[str]) -> list[str]:
        """按原顺序去除重复指令。"""

        return list(dict.fromkeys(values)) #删除重复内容


class Finding(StrictModel):
    """审查流程返回的一条结构化问题。"""

    path: str = Field(min_length=1, max_length=500)
    line: int = Field(ge=1)
    severity: Severity
    category: FindingCategory
    message: str = Field(min_length=1, max_length=2_000)
    suggestion: str = Field(min_length=1, max_length=2_000)


class ModelReviewResult(StrictModel):
    """Agent 结束工具调用后的结构化输出。"""

    summary: str = Field(min_length=1, max_length=2_000)
    findings: list[Finding] = Field(default_factory=list, max_length=20)


class ReviewResponse(StrictModel):
    """包含 Markdown 报告路径的审查响应。"""

    review_id: UUID
    status: Literal["completed", "failed"]
    base_commit: str = Field(min_length=40, max_length=40)
    head_commit: str = Field(min_length=40, max_length=40)
    summary: str = Field(default="", max_length=2_000)
    findings: list[Finding] = Field(default_factory=list, max_length=10)
    markdown_report: Path | None = None
    error: str | None = Field(default=None, max_length=2_000)


class ReviewHistoryRecord(ReviewResponse):
    """单次图运行后保存的 JSON 记录。"""

    created_at: datetime
    repo_path: Path
    base_ref: str
    head_ref: str
    review_focus: list[str] = Field(default_factory=list)
    custom_rules: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    tool_rounds: int = Field(ge=0)
    tool_calls: int = Field(ge=0)


class ReviewHistoryList(StrictModel):
    """按时间倒序排列的审查记录列表。"""

    total: int = Field(ge=0)
    items: list[ReviewHistoryRecord]
