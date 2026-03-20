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

    def get_entries(self, category: str | None = None, level: str | None = None) -> list[dict]:
        results = []
        for e in self.entries:
            if category and not e.category.startswith(category):
                continue
            if level and e.level != level.upper():
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

    def get_all_text(self, category: str | None = None) -> str:
        entries = self.get_entries(category=category)
        return "\n".join(
            f"{e['timestamp']} [{e['level']}] {e['category']}: {e['message']}"
            for e in entries
        )


# Singleton
log_store = LogStore()
