import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LogEntry:
    timestamp: str
    level: str
    category: str
    message: str


class LogStore(logging.Handler):
    """In-memory ring buffer that captures log records for the UI."""

    def __init__(self, max_entries: int = 5000):
        super().__init__()
        self.entries: deque[LogEntry] = deque(maxlen=max_entries)

    def emit(self, record: logging.LogRecord):
        entry = LogEntry(
            timestamp=datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            level=record.levelname,
            category=record.name,
            message=self.format(record),
        )
        self.entries.append(entry)

    def get_entries(
        self,
        category: str | None = None,
        level: str | None = None,
        categories: list[str] | None = None,
        levels: list[str] | None = None,
    ) -> list[dict]:
        category_filters = [item for item in (categories or []) if item]
        level_filters = [item.upper() for item in (levels or []) if item]
        if category and not category_filters:
            category_filters = [category]
        if level and not level_filters:
            level_filters = [level.upper()]

        results = []
        for e in self.entries:
            if category_filters and not any(e.category.startswith(item) for item in category_filters):
                continue
            if level_filters and e.level.upper() not in level_filters:
                continue
            results.append({
                "timestamp": e.timestamp,
                "level": e.level,
                "category": e.category,
                "message": e.message,
            })
        return results

    def get_categories(self) -> list[str]:
        return sorted({e.category for e in self.entries})

    def get_all_text(
        self,
        category: str | None = None,
        level: str | None = None,
        categories: list[str] | None = None,
        levels: list[str] | None = None,
    ) -> str:
        entries = self.get_entries(category=category, level=level, categories=categories, levels=levels)
        return "\n".join(
            f"{e['timestamp']} [{e['level']}] {e['category']}: {e['message']}"
            for e in entries
        )


# Singleton
log_store = LogStore()
