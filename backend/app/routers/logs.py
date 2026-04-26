import re

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from backend.app.utils.log_store import log_store
from backend.app.utils.logging_config import get_log_files, redact_log_text

router = APIRouter(prefix="/api/logs", tags=["logs"])

_LOG_LINE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[(?P<level>[A-Z]+)\] (?P<category>[^:]+): "
)


@router.get("")
async def get_logs(
    category: list[str] = Query(default=[]),
    level: list[str] = Query(default=[]),
):
    return {
        "entries": log_store.get_entries(categories=category, levels=level),
        "categories": log_store.get_categories(),
    }


@router.get("/download")
async def download_logs(
    category: list[str] = Query(default=[]),
    level: list[str] = Query(default=[]),
):
    text = _get_persisted_log_text(categories=category, levels=level)
    if not text:
        text = log_store.get_all_text(categories=category, levels=level)
    return PlainTextResponse(
        content=text,
        headers={"Content-Disposition": "attachment; filename=booksarr.log"},
    )


def _get_persisted_log_text(categories: list[str], levels: list[str]) -> str:
    category_filters = [item for item in categories if item]
    level_filters = {item.upper() for item in levels if item}
    output: list[str] = []
    include_continuation = not category_filters and not level_filters

    for path in sorted(get_log_files(), key=lambda item: item.stat().st_mtime):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        if output:
            output.append("")
        output.append(f"===== {path.name} =====")

        for line in lines:
            line = redact_log_text(line)
            match = _LOG_LINE_PATTERN.match(line)
            if match:
                line_level = match.group("level").upper()
                line_category = match.group("category")
                include_continuation = (
                    (not level_filters or line_level in level_filters)
                    and (not category_filters or any(line_category.startswith(item) for item in category_filters))
                )
            if include_continuation:
                output.append(line)

    return "\n".join(output).strip()
