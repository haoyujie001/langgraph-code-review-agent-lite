"""把每次代码审查的最终结果保存成 JSON 文件，并提供查询单条记录和历史列表的能力。"""

import json
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from code_review_agent_lite.schemas import ReviewHistoryList, ReviewHistoryRecord
from code_review_agent_lite.state import ReviewState


class HistoryStoreError(RuntimeError):
    """历史记录无法保存或解析时抛出。"""


class HistoryNotFoundError(HistoryStoreError):
    """找不到指定审查记录时抛出。"""


class HistoryStore:
    """将每次审查保存为独立 JSON 文件。"""

    def __init__(self, history_dir: Path | str) -> None:
        self.history_dir = Path(history_dir)

    def save_state(self, state: ReviewState) -> ReviewHistoryRecord:
        """将最终图状态原子写入历史记录。"""

        record = ReviewHistoryRecord(
            review_id=state["review_id"],
            created_at=state["created_at"],
            repo_path=state["repo_path"],
            base_ref=state["base_ref"],
            head_ref=state["head_ref"],
            base_commit=state["base_commit"],
            head_commit=state["head_commit"],
            review_focus=state["review_focus"],
            custom_rules=state["custom_rules"],
            changed_files=[item.path for item in state["changed_files"]],
            tool_rounds=state["tool_rounds"],
            tool_calls=state["tool_calls"],
            status=state["status"],
            summary=state["summary"],
            findings=state["findings"],
            markdown_report=state["markdown_report"],
            error=state["error"],
        )
        self.history_dir.mkdir(parents=True, exist_ok=True)
        record_path = self._record_path(record.review_id)
        temporary_path = record_path.with_suffix(".tmp")
        try:
            temporary_path.write_text(
                json.dumps(
                    record.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(record_path)
        except OSError as exc:
            raise HistoryStoreError("审查历史写入失败。") from exc
        return record

    def get(self, review_id: UUID | str) -> ReviewHistoryRecord:
        """按 UUID 加载历史记录。"""

        record_path = self._record_path(review_id)
        if not record_path.is_file():
            raise HistoryNotFoundError(f"未找到审查记录: {review_id}")
        return self._load_record(record_path)

    def list(self, *, limit: int = 20) -> ReviewHistoryList:
        """按时间倒序返回有效记录。"""

        if not self.history_dir.is_dir():
            return ReviewHistoryList(total=0, items=[])

        records: list[ReviewHistoryRecord] = []
        for path in self.history_dir.glob("*.json"):
            try:
                records.append(self._load_record(path))
            except HistoryStoreError:
                # 单个损坏文件不应影响其他历史记录。
                continue
        records.sort(key=lambda item: item.created_at, reverse=True)
        return ReviewHistoryList(total=len(records), items=records[:limit])

    def _record_path(self, review_id: UUID | str) -> Path:
        try:
            normalized_id = UUID(str(review_id)).hex
        except ValueError as exc:
            raise HistoryNotFoundError(f"无效的审查记录 ID: {review_id}") from exc
        return self.history_dir / f"{normalized_id}.json"

    @staticmethod
    def _load_record(path: Path) -> ReviewHistoryRecord:
        try:
            return ReviewHistoryRecord.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, json.JSONDecodeError) as exc:
            raise HistoryStoreError(f"审查历史文件无效: {path.name}") from exc
