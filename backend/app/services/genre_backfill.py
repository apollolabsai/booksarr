import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import async_session
from backend.app.models import Author, Book, Setting
from backend.app.services.genre_normalization import normalize_genres
from backend.app.services.hardcover import HardcoverClient, HardcoverLookupError
from backend.app.services.library_sync import get_api_key

logger = logging.getLogger("booksarr.genre_backfill")

GENRE_BACKFILL_SETTING_KEY = "hardcover_genres_backfill_v1"
GENRE_BACKFILL_COMPLETE = "complete"

_backfill_task: asyncio.Task | None = None


async def _mark_backfill_complete(db: AsyncSession) -> None:
    setting = await db.get(Setting, GENRE_BACKFILL_SETTING_KEY)
    if setting:
        setting.value = GENRE_BACKFILL_COMPLETE
    else:
        db.add(Setting(
            key=GENRE_BACKFILL_SETTING_KEY,
            value=GENRE_BACKFILL_COMPLETE,
        ))
    await db.commit()


async def backfill_missing_genres(
    db: AsyncSession,
    *,
    client_factory: Callable[[str], HardcoverClient] = HardcoverClient,
) -> int:
    marker = await db.get(Setting, GENRE_BACKFILL_SETTING_KEY)
    if marker and marker.value == GENRE_BACKFILL_COMPLETE:
        return 0

    pending_result = await db.execute(
        select(Book.id, Book.hardcover_id, Author.hardcover_id)
        .join(Author, Author.id == Book.author_id)
        .where(
            Book.hardcover_id.is_not(None),
            Book.genres.is_(None),
        )
        .order_by(Book.author_id, Book.id)
    )
    pending_books = list(pending_result.all())
    if not pending_books:
        await _mark_backfill_complete(db)
        return 0

    api_key = await get_api_key(db)
    if not api_key:
        logger.info(
            "Genre backfill deferred: %d book(s) need genres but no Hardcover API key is configured",
            len(pending_books),
        )
        return 0

    books_by_author: dict[int, list[tuple[int, int]]] = defaultdict(list)
    books_without_hardcover_author: list[tuple[int, int]] = []
    for book_id, book_hardcover_id, author_hardcover_id in pending_books:
        if author_hardcover_id:
            books_by_author[author_hardcover_id].append((book_id, book_hardcover_id))
        else:
            books_without_hardcover_author.append((book_id, book_hardcover_id))

    updated = 0
    failures = 0
    client = client_factory(api_key)
    try:
        for author_hardcover_id, local_books in books_by_author.items():
            try:
                hardcover_books = await client.get_author_books(author_hardcover_id)
                hardcover_books_by_id = {book.id: book for book in hardcover_books}
                genre_updates: list[tuple[int, str]] = []

                for local_book_id, local_hardcover_id in local_books:
                    hardcover_book = hardcover_books_by_id.get(local_hardcover_id)
                    if hardcover_book is None:
                        hardcover_book = await client.get_book(local_hardcover_id)
                    if hardcover_book is None:
                        failures += 1
                        logger.warning(
                            "Genre backfill could not find Hardcover book %s for local book %s",
                            local_hardcover_id,
                            local_book_id,
                        )
                        continue
                    genre_updates.append((
                        local_book_id,
                        json.dumps(normalize_genres(hardcover_book.genres)),
                    ))

                for local_book_id, genres_json in genre_updates:
                    await db.execute(
                        update(Book)
                        .where(Book.id == local_book_id)
                        .values(genres=genres_json)
                    )

                await db.commit()
                updated += len(genre_updates)
            except HardcoverLookupError as exc:
                failures += 1
                await db.rollback()
                logger.warning(
                    "Genre backfill deferred for Hardcover author %s: %s",
                    author_hardcover_id,
                    exc,
                )
            except Exception:
                failures += 1
                await db.rollback()
                logger.exception(
                    "Genre backfill failed for Hardcover author %s",
                    author_hardcover_id,
                )

        for local_book_id, local_hardcover_id in books_without_hardcover_author:
            try:
                hardcover_book = await client.get_book(local_hardcover_id)
                if hardcover_book is None:
                    failures += 1
                    continue
                await db.execute(
                    update(Book)
                    .where(Book.id == local_book_id)
                    .values(genres=json.dumps(normalize_genres(hardcover_book.genres)))
                )
                await db.commit()
                updated += 1
            except HardcoverLookupError as exc:
                failures += 1
                await db.rollback()
                logger.warning(
                    "Genre backfill deferred for Hardcover book %s: %s",
                    local_hardcover_id,
                    exc,
                )
            except Exception:
                failures += 1
                await db.rollback()
                logger.exception(
                    "Genre backfill failed for Hardcover book %s",
                    local_hardcover_id,
                )
    finally:
        await client.close()

    remaining = await db.scalar(
        select(func.count())
        .select_from(Book)
        .where(
            Book.hardcover_id.is_not(None),
            Book.genres.is_(None),
        )
    )
    if not remaining:
        await _mark_backfill_complete(db)
        logger.info("Genre backfill complete: updated %d book(s)", updated)
    else:
        logger.warning(
            "Genre backfill incomplete: updated %d book(s), %d remaining, %d failure(s)",
            updated,
            remaining,
            failures,
        )

    return updated


async def _run_genre_backfill() -> None:
    try:
        async with async_session() as db:
            await backfill_missing_genres(db)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Genre backfill task failed")


async def start_genre_backfill() -> None:
    global _backfill_task
    if _backfill_task and not _backfill_task.done():
        return
    _backfill_task = asyncio.create_task(_run_genre_backfill())


async def stop_genre_backfill() -> None:
    global _backfill_task
    if _backfill_task and not _backfill_task.done():
        _backfill_task.cancel()
        try:
            await _backfill_task
        except asyncio.CancelledError:
            pass
    _backfill_task = None
