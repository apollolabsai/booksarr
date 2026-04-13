import asyncio
import json
import logging
import re
import shutil
import ssl
import struct
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from socket import inet_ntoa
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from backend.app.config import BOOKS_DIR, DOWNLOADS_DIR, IRC_STATE_DIR
from backend.app.database import async_session
from backend.app.models import (
    Author,
    Book,
    IrcBulkDownloadBatch,
    IrcBulkDownloadItem,
    IrcDownloadJob,
    IrcSearchJob,
    IrcSearchResult,
    Setting,
)
from backend.app.services.irc_parser import (
    build_expected_result_filename,
    build_search_command,
    command_matches_filename,
    normalize_query_key,
    normalize_query_text,
    parse_search_results_archive,
    result_archive_matches_query,
)
from backend.app.services.matcher import normalize_title
from backend.app.utils.opf_parser import parse_epub_opf

logger = logging.getLogger("booksarr.irc")

IRC_MAX_TIMEOUT_SECONDS = 60
IRC_CONNECT_TIMEOUT_SECONDS = 30
IRC_DCC_CONNECT_TIMEOUT_SECONDS = 15
IRC_DCC_WAIT_TIMEOUT_SECONDS = 30
IRC_DCC_BOOK_IDLE_TIMEOUT_SECONDS = 180
IRC_DCC_CHUNK_TIMEOUT_SECONDS = 10
IRC_DCC_TRAILING_READ_TIMEOUT_SECONDS = 1.0
IRC_DCC_MAX_TRAILING_BYTES = 1024 * 1024
IRC_DCC_PROGRESS_UPDATE_INTERVAL_SECONDS = 1.0
IRC_DCC_PROGRESS_UPDATE_MIN_BYTES = 512 * 1024
BULK_MAX_DOWNLOAD_ATTEMPTS = 3

BULK_BATCH_ACTIVE_STATUSES = {"queued", "running", "pausing", "cancelling"}
BULK_ITEM_ACTIVE_STATUSES = {
    "searching",
    "downloading_search_results",
    "choosing_best_option",
    "downloading_book",
    "extracting",
    "importing",
}
_AUDIO_TOKENS = {
    "audio",
    "audiobook",
    "audio book",
    "audible",
    "unabridged",
    "abridged",
    "narrated",
}
_BULK_FILE_TYPE_KEYS = ("epub", "mobi", "zip", "rar", "audiobook")
_DIRECT_BULK_FILE_TYPES = {"epub", "mobi", "zip", "rar"}
_AUDIOBOOK_MIN_SIZE_MB = 15.0

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_reader_task: asyncio.Task | None = None
_archive_task: asyncio.Task | None = None
_book_download_task: asyncio.Task | None = None
_writer: asyncio.StreamWriter | None = None


@dataclass
class IrcRuntimeState:
    enabled: bool = False
    desired_connection: bool = False
    connected: bool = False
    joined_channel: bool = False
    state: str = "stopped"
    server: str | None = None
    channel: str | None = None
    nickname: str | None = None
    active_search_job_id: int | None = None
    active_download_job_id: int | None = None
    last_message: str | None = None
    last_error: str | None = None


_runtime = IrcRuntimeState()
_IRC_COLOR_RE = re.compile(r"\x03(?:\d{1,2}(?:,\d{1,2})?)?")
_IRC_FORMAT_RE = re.compile(r"[\x02\x0f\x16\x1d\x1f]")
_IRC_NICK_PREFIX_CHARS = "~&@%+"
_vpn_bind_ip: str | None = None
_online_channel_nicks: dict[str, str] = {}


def get_runtime_status() -> IrcRuntimeState:
    return IrcRuntimeState(**asdict(_runtime))


def get_online_irc_nicks() -> list[str]:
    return sorted(_online_channel_nicks.values(), key=str.lower)


def is_bot_online(bot_name: str | None) -> bool | None:
    normalized = _normalize_irc_nick(bot_name)
    if not normalized:
        return None
    return normalized in _online_channel_nicks


def _normalize_irc_nick(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    return cleaned.lstrip(_IRC_NICK_PREFIX_CHARS).split("!", 1)[0].strip().lower()


def _track_online_nick(nick: str | None):
    normalized = _normalize_irc_nick(nick)
    if not normalized:
        return
    display = (nick or "").strip().lstrip(_IRC_NICK_PREFIX_CHARS).split("!", 1)[0].strip()
    _online_channel_nicks[normalized] = display or normalized


def _forget_online_nick(nick: str | None):
    normalized = _normalize_irc_nick(nick)
    if not normalized:
        return
    _online_channel_nicks.pop(normalized, None)


def _replace_online_nick(old_nick: str | None, new_nick: str | None):
    _forget_online_nick(old_nick)
    _track_online_nick(new_nick)


def _reset_online_nicks():
    _online_channel_nicks.clear()


async def start_irc_worker():
    global _worker_task, _stop_event
    if _worker_task and not _worker_task.done():
        logger.info("IRC worker already running")
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("IRC worker started")


async def stop_irc_worker():
    global _worker_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    _worker_task = None
    _stop_event = None
    _runtime.connected = False
    _runtime.joined_channel = False
    _reset_online_nicks()
    _runtime.state = "stopped"
    await _close_connection("Worker shutdown")
    logger.info("IRC worker stopped")


async def request_connect():
    _runtime.desired_connection = True
    _runtime.last_message = "Connection requested from UI"
    logger.info("IRC connection requested")


async def request_disconnect():
    global _vpn_bind_ip
    _runtime.desired_connection = False
    await _close_connection("Disconnect requested from UI")
    try:
        from backend.app.services.vpn_manager import (
            get_vpn_interface_ip,
            get_vpn_public_ip,
            get_vpn_region,
            stop_vpn,
        )

        tunnel_ip = get_vpn_interface_ip()
        if tunnel_ip:
            logger.info(
                "Stopping VPN after IRC disconnect: region=%s tunnel_ip=%s public_ip=%s",
                get_vpn_region() or "unknown",
                tunnel_ip,
                get_vpn_public_ip() or "unknown",
            )
            await stop_vpn()
    except Exception as exc:
        logger.warning("Failed to stop VPN during IRC disconnect: %s", exc)
    _vpn_bind_ip = None
    _reset_online_nicks()
    _runtime.state = "idle"
    _runtime.last_message = "Disconnected on request"
    logger.info("IRC disconnect requested")


async def _worker_loop():
    while _stop_event and not _stop_event.is_set():
        try:
            settings = await _load_irc_settings()
            _runtime.enabled = settings["enabled"]
            _runtime.server = settings["server"] or None
            _runtime.channel = settings["channel"] or None
            _runtime.nickname = settings["nickname"] or None

            queued_searches, queued_downloads = await _get_queue_counts()
            _runtime.active_search_job_id = None
            _runtime.active_download_job_id = None

            if not settings["enabled"]:
                if _runtime.state != "disabled":
                    _runtime.state = "disabled"
                    _runtime.last_error = None
                    _runtime.last_message = "IRC integration disabled in settings"
                    logger.info("IRC worker idle: integration disabled")
                await _close_connection("IRC disabled in settings")
                await asyncio.sleep(5)
                continue

            if not _runtime.desired_connection:
                if _runtime.state not in {"idle", "connect_failed", "invalid_config"}:
                    _runtime.state = "idle"
                    _runtime.last_message = "Waiting for user to connect"
                    logger.info("IRC worker idle: waiting for connect request")
                await _close_connection("Waiting for user to request connection")
                await asyncio.sleep(5)
                continue

            if not settings["server"] or not settings["channel"] or not settings["nickname"]:
                _runtime.state = "invalid_config"
                _runtime.last_error = "Server, nickname, and channel are required"
                logger.warning("IRC worker cannot connect: missing server, nickname, or channel")
                await _close_connection("Missing IRC configuration")
                await asyncio.sleep(5)
                continue

            if (
                settings["vpn_enabled"]
                and (
                    not str(settings["vpn_username"]).strip()
                    or not str(settings["vpn_password"]).strip()
                )
            ):
                _runtime.state = "invalid_config"
                _runtime.last_error = "VPN username and password are required when VPN is enabled"
                logger.warning("IRC worker cannot connect: incomplete VPN configuration")
                await _close_connection("Missing VPN configuration")
                await asyncio.sleep(5)
                continue

            if not _runtime.connected:
                await _attempt_connection(settings)
            else:
                await _expire_stale_search_jobs()
                await _expire_stale_download_jobs()
                await _process_bulk_batches()
                _runtime.state = "connected"
                _runtime.last_message = (
                    f"Connected and monitoring jobs ({queued_searches} search, {queued_downloads} download queued)"
                )
                await _process_next_search_job(settings)
                await _process_next_download_job(settings)

            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _runtime.state = "error"
            _runtime.last_error = str(exc)
            logger.exception("IRC worker loop failed: %s", exc)
            await _close_connection(f"Worker loop error: {exc}")
            await asyncio.sleep(10)


async def _attempt_connection(settings: dict[str, object]):
    global _reader_task, _writer, _vpn_bind_ip
    server = str(settings["server"])
    port = int(settings["port"])
    use_tls = bool(settings["use_tls"])
    nickname = str(settings["nickname"])
    username = str(settings["username"] or settings["nickname"])
    real_name = str(settings["real_name"] or settings["nickname"])
    channel = str(settings["channel"])

    _runtime.state = "connecting"
    _runtime.last_message = f"Connecting to {server}:{port}"

    bind_ip: str | None = None
    if settings["vpn_enabled"]:
        from backend.app.services.vpn_manager import (
            get_vpn_interface_ip,
            get_vpn_public_ip,
            get_vpn_region,
            start_vpn,
        )

        _runtime.last_message = f"Starting VPN ({settings['vpn_region']}) before connecting to {server}:{port}"
        logger.info(
            "IRC connect attempt: starting VPN region=%s before connecting to server=%s port=%s",
            settings["vpn_region"],
            server,
            port,
        )
        requested_region = str(settings["vpn_region"])
        existing_ip = get_vpn_interface_ip()
        existing_region = get_vpn_region()
        existing_public_ip = get_vpn_public_ip()
        if existing_ip and existing_region == requested_region:
            bind_ip = existing_ip
            logger.info(
                "VPN already running, reusing: region=%s tunnel_ip=%s public_ip=%s",
                existing_region or "unknown",
                bind_ip,
                existing_public_ip or "unknown",
            )
        else:
            if existing_ip:
                logger.info(
                    "VPN region changed, restarting tunnel: current_region=%s requested_region=%s tunnel_ip=%s public_ip=%s",
                    existing_region or "unknown",
                    requested_region,
                    existing_ip,
                    existing_public_ip or "unknown",
                )
            try:
                bind_ip = await start_vpn(
                    username=str(settings["vpn_username"]),
                    password=str(settings["vpn_password"]),
                    region=requested_region,
                )
            except Exception as vpn_exc:
                _runtime.state = "connect_failed"
                _runtime.last_error = f"VPN failed: {vpn_exc}"
                _runtime.last_message = f"VPN connection failed: {vpn_exc}"
                _runtime.desired_connection = False
                logger.warning("VPN start failed: %s", vpn_exc)
                return
        vpn_public_ip = get_vpn_public_ip()
        _vpn_bind_ip = bind_ip
        logger.info(
            "VPN ready for IRC connect: region=%s tunnel_ip=%s public_ip=%s",
            requested_region,
            bind_ip,
            vpn_public_ip or "unknown",
        )
        _runtime.last_message = f"VPN connected ({bind_ip}), connecting to {server}:{port}"

    logger.info(
        "IRC connect attempt: server=%s port=%s tls=%s nick=%s channel=%s vpn=%s bind_ip=%s",
        server,
        port,
        use_tls,
        nickname,
        channel,
        settings["vpn_enabled"],
        bind_ip,
    )

    try:
        ssl_context = ssl.create_default_context() if use_tls else None
        reader, writer = await asyncio.wait_for(
            _open_tcp_connection(
                server,
                port,
                ssl_context=ssl_context,
                server_hostname=server if use_tls else None,
                bind_ip=bind_ip,
                log_prefix="IRC control connection",
            ),
            timeout=IRC_CONNECT_TIMEOUT_SECONDS,
        )
        _writer = writer
        _send_raw_line(writer, f"NICK {nickname}")
        _send_raw_line(writer, f"USER {username} 0 * :{real_name}")

        _runtime.connected = True
        _runtime.joined_channel = False
        _runtime.state = "registering"
        _runtime.last_error = None
        _runtime.last_message = f"Connected to {server}; waiting for IRC registration before joining {channel}"
        _reader_task = asyncio.create_task(_reader_loop(reader))
        logger.info("IRC TCP connection established to %s; waiting for server registration", server)
    except Exception as exc:
        await _close_connection(f"Connection failed: {exc}")
        raw_message = str(exc).strip() or exc.__class__.__name__
        _runtime.state = "connect_failed"
        _runtime.last_error = raw_message
        _runtime.last_message = f"Connection failed: {raw_message}"
        logger.warning("IRC connection failed: %s", raw_message)


async def _process_bulk_batches():
    async with async_session() as db:
        batch_result = await db.execute(
            select(IrcBulkDownloadBatch)
            .options(
                selectinload(IrcBulkDownloadBatch.items).selectinload(IrcBulkDownloadItem.book).selectinload(Book.author),
                selectinload(IrcBulkDownloadBatch.items).selectinload(IrcBulkDownloadItem.search_job).selectinload(IrcSearchJob.results),
                selectinload(IrcBulkDownloadBatch.items).selectinload(IrcBulkDownloadItem.download_job),
                selectinload(IrcBulkDownloadBatch.items).selectinload(IrcBulkDownloadItem.selected_search_result),
            )
            .where(IrcBulkDownloadBatch.status.in_(BULK_BATCH_ACTIVE_STATUSES))
            .order_by(IrcBulkDownloadBatch.created_at.asc())
        )
        batches = batch_result.scalars().all()
        if not batches:
            return

        now = datetime.utcnow()
        updated_anything = False

        for batch in batches:
            items = sorted(batch.items, key=lambda item: item.position)

            active_item = next((item for item in items if item.status in BULK_ITEM_ACTIVE_STATUSES), None)
            if active_item is not None:
                changed = await _advance_bulk_item(batch, active_item, now, db)
                updated_anything = updated_anything or changed
                break

            if batch.status == "pausing":
                if any(item.status == "queued" for item in items):
                    batch.status = "paused"
                    batch.updated_at = now
                    logger.info("IRC bulk batch %s paused after current book completed", batch.request_id)
                    updated_anything = True
                    break
                batch.status = "completed"
                batch.updated_at = now
                batch.completed_at = now
                logger.info(
                    "IRC bulk batch %s completed while honoring pause request: total=%s completed=%s failed=%s",
                    batch.request_id,
                    len(items),
                    sum(1 for item in items if item.status == "completed"),
                    sum(1 for item in items if item.status == "failed"),
                )
                updated_anything = True
                break

            if batch.status == "cancelling":
                batch.status = "cancelled"
                batch.updated_at = now
                batch.completed_at = now
                logger.info(
                    "IRC bulk batch %s cancelled after current book completed: total=%s completed=%s failed=%s",
                    batch.request_id,
                    len(items),
                    sum(1 for item in items if item.status == "completed"),
                    sum(1 for item in items if item.status == "failed"),
                )
                updated_anything = True
                break

            queued_item = next((item for item in items if item.status == "queued"), None)
            if queued_item is not None:
                if batch.status != "running":
                    batch.status = "running"
                    batch.updated_at = now
                await _queue_bulk_item_search(batch, queued_item, now, db)
                updated_anything = True
                break

            if batch.status != "completed":
                batch.status = "completed"
                batch.updated_at = now
                batch.completed_at = now
                logger.info(
                    "IRC bulk batch %s completed: total=%s completed=%s failed=%s",
                    batch.request_id,
                    len(items),
                    sum(1 for item in items if item.status == "completed"),
                    sum(1 for item in items if item.status == "failed"),
                )
                updated_anything = True

        if updated_anything:
            await db.commit()


async def _advance_bulk_item(
    batch: IrcBulkDownloadBatch,
    item: IrcBulkDownloadItem,
    now: datetime,
    db,
) -> bool:
    if item.download_job is not None:
        download_status = item.download_job.status
        if download_status in {"queued", "sent", "waiting_dcc", "downloading", "downloaded"} and item.status != "downloading_book":
            item.status = "downloading_book"
            item.updated_at = now
            return True
        if download_status in {"extracting", "extracted"} and item.status != "extracting":
            item.status = "extracting"
            item.updated_at = now
            return True
        if download_status in {"importing", "refreshing_library"} and item.status != "importing":
            item.status = "importing"
            item.updated_at = now
            return True
        if download_status == "moved":
            item.status = "completed"
            item.error_message = None
            item.updated_at = now
            item.completed_at = now
            logger.info(
                "IRC bulk item %s completed: batch=%s book_id=%s selected=%r",
                item.id,
                batch.request_id,
                item.book_id,
                item.selected_result_label,
            )
            return True
        if download_status == "failed":
            attempted_ids = _parse_attempted_ids(item.attempted_result_ids)
            attempts_used = len(attempted_ids)
            can_retry = (
                attempts_used < BULK_MAX_DOWNLOAD_ATTEMPTS
                and _has_next_bulk_result_candidate(item)
            )
            if can_retry:
                previous_download_job_id = item.download_job_id
                error_message = item.download_job.error_message
                item.status = "choosing_best_option"
                item.error_message = error_message
                item.download_job_id = None
                item.download_job = None
                item.updated_at = now
                logger.warning(
                    "IRC bulk item %s retrying after download failure: batch=%s book_id=%s previous_download_job_id=%s error=%s",
                    item.id,
                    batch.request_id,
                    item.book_id,
                    previous_download_job_id,
                    error_message,
                )
            else:
                item.status = "failed"
                last_error = item.download_job.error_message or "Download failed"
                if attempts_used >= BULK_MAX_DOWNLOAD_ATTEMPTS:
                    item.error_message = (
                        f"Failed after {BULK_MAX_DOWNLOAD_ATTEMPTS} unsuccessful download attempts. "
                        f"Last error: {last_error}"
                    )
                else:
                    item.error_message = last_error
                item.updated_at = now
                item.completed_at = now
                logger.warning(
                    "IRC bulk item %s failed after exhausting candidates: batch=%s book_id=%s error=%s",
                    item.id,
                    batch.request_id,
                    item.book_id,
                    item.error_message,
                )
            return True

    if item.search_job is not None:
        if item.search_job.status == "downloading_results" and item.status != "downloading_search_results":
            item.status = "downloading_search_results"
            item.updated_at = now
            return True
        if item.search_job.status == "failed":
            item.status = "failed"
            item.error_message = item.search_job.error_message or "Search failed"
            item.updated_at = now
            item.completed_at = now
            logger.warning(
                "IRC bulk item %s failed during search: batch=%s book_id=%s error=%s",
                item.id,
                batch.request_id,
                item.book_id,
                item.error_message,
            )
            return True
        if (
            item.search_job.status == "results_ready"
            and item.download_job is None
            and item.status != "choosing_best_option"
        ):
            item.status = "choosing_best_option"
            item.updated_at = now
            return True

    if item.status == "choosing_best_option":
        return await _queue_best_download_for_bulk_item(batch, item, now, db)

    return False


async def _queue_bulk_item_search(
    batch: IrcBulkDownloadBatch,
    item: IrcBulkDownloadItem,
    now: datetime,
    db,
) -> None:
    query_text = normalize_query_text(item.query_text or _bulk_query_for_book(item.book))
    normalized_query = normalize_query_key(query_text)
    if not query_text or not normalized_query:
        item.status = "failed"
        item.error_message = "Search query could not be built for this book"
        item.updated_at = now
        item.completed_at = now
        logger.warning(
            "IRC bulk item %s failed before search: batch=%s book_id=%s reason=invalid_query",
            item.id,
            batch.request_id,
            item.book_id,
        )
        return

    item.query_text = query_text
    item.status = "searching"
    item.error_message = None
    item.selected_result_label = None
    item.updated_at = now

    job = IrcSearchJob(
        book_id=item.book_id,
        query_text=query_text,
        normalized_query=normalized_query,
        status="queued",
        auto_download=False,
        bulk_request_id=batch.request_id,
        bulk_item_id=item.id,
        request_message=build_search_command(query_text),
        expected_result_filename=build_expected_result_filename(query_text),
    )
    db.add(job)
    await db.flush()
    item.search_job_id = job.id
    item.search_job = job
    logger.info(
        "IRC bulk item %s queued search: batch=%s book_id=%s position=%s query=%r",
        item.id,
        batch.request_id,
        item.book_id,
        item.position,
        query_text,
    )


async def _queue_best_download_for_bulk_item(
    batch: IrcBulkDownloadBatch,
    item: IrcBulkDownloadItem,
    now: datetime,
    db,
) -> bool:
    if item.search_job is None or not item.search_job.results:
        item.status = "failed"
        item.error_message = "Search returned no parsed results"
        item.updated_at = now
        item.completed_at = now
        logger.warning(
            "IRC bulk item %s failed: batch=%s book_id=%s reason=no_parsed_results",
            item.id,
            batch.request_id,
            item.book_id,
        )
        return True

    attempted_ids = _parse_attempted_ids(item.attempted_result_ids)
    previous_result = next(
        (result for result in item.search_job.results if result.id == item.selected_search_result_id),
        None,
    )
    prefer_different_bot = bool(item.error_message and "timed out" in item.error_message.lower())
    selected_result = _choose_best_bulk_result(
        book=item.book,
        results=item.search_job.results,
        attempted_ids=attempted_ids,
        previous_result=previous_result,
        prefer_different_bot=prefer_different_bot,
        file_type_preferences=batch.file_type_preferences,
    )
    if selected_result is None:
        item.status = "failed"
        item.error_message = item.error_message or "No suitable ebook result remained after filtering"
        item.updated_at = now
        item.completed_at = now
        logger.warning(
            "IRC bulk item %s failed: batch=%s book_id=%s reason=no_suitable_result",
            item.id,
            batch.request_id,
            item.book_id,
        )
        return True

    for row in item.search_job.results:
        row.selected = row.id == selected_result.id

    attempted_ids.append(selected_result.id)
    item.attempted_result_ids = ",".join(str(value) for value in attempted_ids)
    item.selected_search_result_id = selected_result.id
    item.selected_result_label = selected_result.raw_line or selected_result.display_name
    item.status = "downloading_book"
    item.updated_at = now

    download_job = IrcDownloadJob(
        book_id=item.book_id,
        search_job_id=item.search_job_id,
        search_result_id=selected_result.id,
        status="queued",
        bulk_request_id=batch.request_id,
        bulk_item_id=item.id,
        request_message=selected_result.download_command,
        dcc_filename=selected_result.display_name,
    )
    db.add(download_job)
    await db.flush()
    item.download_job_id = download_job.id
    item.download_job = download_job

    logger.info(
        "IRC bulk item %s chose search result: batch=%s book_id=%s result_id=%s bot=%r label=%r attempts=%s",
        item.id,
        batch.request_id,
        item.book_id,
        selected_result.id,
        selected_result.bot_name,
        selected_result.display_name,
        len(attempted_ids),
    )
    return True


def _bulk_query_for_book(book: Book | None) -> str:
    if book is None:
        return ""
    author_name = book.author.name if book.author else ""
    return " ".join(part for part in [author_name, book.title] if part).strip()


def _parse_attempted_ids(value: str | None) -> list[int]:
    if not value:
        return []
    parsed: list[int] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parsed.append(int(chunk))
        except ValueError:
            continue
    return parsed


def normalize_bulk_file_type_preferences(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, list):
        value = []

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        if key not in _BULK_FILE_TYPE_KEYS or key in seen:
            continue
        seen.add(key)
        normalized.append({
            "key": key,
            "enabled": bool(item.get("enabled", True)),
        })

    for key in _BULK_FILE_TYPE_KEYS:
        if key in seen:
            continue
        normalized.append({"key": key, "enabled": True})
    return normalized


def serialize_bulk_file_type_preferences(value: Any) -> str:
    return json.dumps(normalize_bulk_file_type_preferences(value), separators=(",", ":"))


def _has_next_bulk_result_candidate(item: IrcBulkDownloadItem) -> bool:
    if item.search_job is None or not item.search_job.results:
        return False
    attempted_ids = _parse_attempted_ids(item.attempted_result_ids)
    previous_result = next(
        (result for result in item.search_job.results if result.id == item.selected_search_result_id),
        None,
    )
    return _choose_best_bulk_result(
        book=item.book,
        results=item.search_job.results,
        attempted_ids=attempted_ids,
        previous_result=previous_result,
        prefer_different_bot=True,
        file_type_preferences=item.batch.file_type_preferences if item.batch is not None else None,
    ) is not None


def _choose_best_bulk_result(
    *,
    book: Book | None,
    results: list[IrcSearchResult],
    attempted_ids: list[int],
    previous_result: IrcSearchResult | None,
    prefer_different_bot: bool,
    file_type_preferences: Any = None,
) -> IrcSearchResult | None:
    normalized_preferences = normalize_bulk_file_type_preferences(file_type_preferences)
    enabled_keys = [item["key"] for item in normalized_preferences if item["enabled"]]
    if not enabled_keys:
        return None
    priority_by_key = {
        key: len(enabled_keys) - index
        for index, key in enumerate(enabled_keys)
    }

    candidates = []
    attempted_set = set(attempted_ids)
    for result in results:
        if result.id in attempted_set:
            continue
        matched_type = _classify_bulk_result_type(result)
        if matched_type is None:
            continue
        priority_rank = priority_by_key.get(matched_type)
        if priority_rank is None:
            continue
        score = _score_bulk_result(book, result, matched_type)
        if score <= -1000:
            continue
        candidates.append(((priority_rank, score, -result.result_index), result))

    if not candidates:
        return None

    online_candidates = [
        (score, result) for score, result in candidates
        if is_bot_online(result.bot_name)
    ]
    if online_candidates:
        candidates = online_candidates

    candidates.sort(key=lambda item: item[0], reverse=True)
    if prefer_different_bot and previous_result and previous_result.bot_name:
        different_bot = [
            (score, result) for score, result in candidates
            if result.bot_name and result.bot_name != previous_result.bot_name
        ]
        if different_bot:
            return different_bot[0][1]

    return candidates[0][1]


def _classify_bulk_result_type(result: IrcSearchResult) -> str | None:
    display_name = (result.display_name or result.download_command or "").lower()
    file_format = (result.file_format or Path(result.display_name or "").suffix.lstrip(".")).lower()
    size_mb = _parse_size_to_megabytes(result.file_size_text)
    if any(token in display_name for token in _AUDIO_TOKENS):
        if size_mb is not None and size_mb > _AUDIOBOOK_MIN_SIZE_MB:
            return "audiobook"
    if file_format in _DIRECT_BULK_FILE_TYPES:
        return file_format
    return None


def _score_bulk_result(book: Book | None, result: IrcSearchResult, matched_type: str) -> int:
    score = {
        "epub": 120,
        "mobi": 100,
        "zip": 90,
        "rar": 80,
        "audiobook": 70,
    }.get(matched_type, 0)

    size_mb = _parse_size_to_megabytes(result.file_size_text)
    if size_mb is not None:
        if matched_type == "audiobook":
            if size_mb <= _AUDIOBOOK_MIN_SIZE_MB:
                return -5000
            if size_mb > 1500:
                score -= 80
            elif size_mb < 40:
                score -= 20
        else:
            if size_mb > 100:
                score -= 250
            elif size_mb > 25:
                score -= 75
            elif size_mb < 0.1:
                score -= 75

    if book is None:
        return score

    normalized_book_title = normalize_title(book.title or "")
    normalized_result_title = normalize_title(result.normalized_title or result.display_name or "")
    if normalized_book_title and normalized_result_title:
        if normalized_book_title == normalized_result_title:
            score += 120
        else:
            book_tokens = set(normalized_book_title.split())
            result_tokens = set(normalized_result_title.split())
            intersection = len(book_tokens & result_tokens)
            score += min(90, intersection * 20)
            if normalized_book_title in normalized_result_title or normalized_result_title in normalized_book_title:
                score += 40

    author_name = book.author.name if book and book.author else ""
    normalized_author = normalize_title(author_name)
    normalized_result_author = normalize_title(result.normalized_author or "")
    if normalized_author and normalized_result_author:
        if normalized_author == normalized_result_author:
            score += 60
        else:
            author_tokens = set(normalized_author.split())
            result_author_tokens = set(normalized_result_author.split())
            score += min(40, len(author_tokens & result_author_tokens) * 12)

    return score


def _parse_size_to_megabytes(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMG])B?", value.strip(), re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "K":
        return amount / 1024
    if unit == "M":
        return amount
    if unit == "G":
        return amount * 1024
    return None


async def _process_next_search_job(settings: dict[str, object]):
    if not _runtime.connected or not _runtime.joined_channel or _writer is None:
        return

    async with async_session() as db:
        active_bulk_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.bulk_item_id.is_not(None),
                IrcSearchJob.status.in_(["sent", "waiting_dcc", "downloading_results"]),
            ).order_by(IrcSearchJob.created_at.asc())
        )
        active_job = active_bulk_result.scalars().first()
        if active_job:
            _runtime.active_search_job_id = active_job.id
            _runtime.last_message = (
                f"Search job {active_job.id} waiting for DCC result archive for '{active_job.query_text}'"
            )
            return

        active_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.status.in_(["sent", "waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.created_at.asc())
        )
        active_job = active_result.scalars().first()
        if active_job:
            _runtime.active_search_job_id = active_job.id
            _runtime.last_message = (
                f"Search job {active_job.id} waiting for DCC result archive for '{active_job.query_text}'"
            )
            return

        queued_bulk_result = await db.execute(
            select(IrcSearchJob)
            .where(IrcSearchJob.bulk_item_id.is_not(None), IrcSearchJob.status == "queued")
            .order_by(IrcSearchJob.created_at.asc())
        )
        job = queued_bulk_result.scalars().first()
        if job is None:
            queued_result = await db.execute(
            select(IrcSearchJob).where(IrcSearchJob.status == "queued").order_by(IrcSearchJob.created_at.asc())
            )
            job = queued_result.scalars().first()
        if job is None:
            _runtime.active_search_job_id = None
            return

        job.query_text = normalize_query_text(job.query_text)
        job.request_message = build_search_command(job.query_text)
        job.expected_result_filename = build_expected_result_filename(job.query_text)
        job.status = "sent"
        job.updated_at = datetime.utcnow()
        _runtime.active_search_job_id = job.id

        logger.info(
            "IRC search job %s dispatching: bulk_request_id=%s query='%s' expected_result='%s'",
            job.id,
            job.bulk_request_id,
            job.query_text,
            job.expected_result_filename,
        )
        await db.commit()

        await _send_channel_message(str(settings["channel"]), job.request_message)

        job.status = "waiting_dcc"
        job.updated_at = datetime.utcnow()
        _runtime.last_message = (
            f"Search job {job.id} sent to {settings['channel']}; waiting for DCC result archive"
        )
        await db.commit()
        logger.info(
            "IRC search job %s is now waiting for a DCC result archive that matches query '%s' (bulk_request_id=%s)",
            job.id,
            job.query_text,
            job.bulk_request_id,
        )


async def _process_next_download_job(settings: dict[str, object]):
    if not _runtime.connected or not _runtime.joined_channel or _writer is None:
        return

    async with async_session() as db:
        active_bulk_search_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.bulk_item_id.is_not(None),
                IrcSearchJob.status.in_(["sent", "waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.created_at.asc())
        )
        active_search_job = active_bulk_search_result.scalars().first()
        if active_search_job is not None:
            return

        active_search_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.status.in_(["sent", "waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.created_at.asc())
        )
        active_search_job = active_search_result.scalars().first()
        if active_search_job is not None:
            return

        active_bulk_download_result = await db.execute(
            select(IrcDownloadJob).where(
                IrcDownloadJob.bulk_item_id.is_not(None),
                IrcDownloadJob.status.in_([
                    "sent",
                    "waiting_dcc",
                    "downloading",
                    "extracting",
                    "importing",
                    "refreshing_library",
                ])
            ).order_by(IrcDownloadJob.created_at.asc())
        )
        active_download_job = active_bulk_download_result.scalars().first()
        if active_download_job is not None:
            _runtime.active_download_job_id = active_download_job.id
            _runtime.last_message = (
                f"Download job {active_download_job.id} waiting for DCC file offer"
            )
            return

        active_download_result = await db.execute(
            select(IrcDownloadJob).where(
                IrcDownloadJob.status.in_([
                    "sent",
                    "waiting_dcc",
                    "downloading",
                    "extracting",
                    "importing",
                    "refreshing_library",
                ])
            ).order_by(IrcDownloadJob.created_at.asc())
        )
        active_download_job = active_download_result.scalars().first()
        if active_download_job is not None:
            _runtime.active_download_job_id = active_download_job.id
            _runtime.last_message = (
                f"Download job {active_download_job.id} waiting for DCC file offer"
            )
            return

        queued_bulk_result = await db.execute(
            select(IrcDownloadJob)
            .where(IrcDownloadJob.bulk_item_id.is_not(None), IrcDownloadJob.status == "queued")
            .order_by(IrcDownloadJob.created_at.asc())
        )
        job = queued_bulk_result.scalars().first()
        if job is None:
            queued_result = await db.execute(
                select(IrcDownloadJob).where(IrcDownloadJob.status == "queued").order_by(IrcDownloadJob.created_at.asc())
            )
            job = queued_result.scalars().first()
        if job is None:
            _runtime.active_download_job_id = None
            return

        if not job.request_message:
            job.status = "failed"
            job.error_message = "Download job did not have a request command"
            job.updated_at = datetime.utcnow()
            job.completed_at = datetime.utcnow()
            await db.commit()
            logger.warning("IRC download job %s failed: missing request command", job.id)
            return

        job.status = "sent"
        job.updated_at = datetime.utcnow()
        _runtime.active_download_job_id = job.id

        logger.info(
            "IRC download job %s dispatching: bulk_request_id=%s search_job_id=%s search_result_id=%s command=%r",
            job.id,
            job.bulk_request_id,
            job.search_job_id,
            job.search_result_id,
            job.request_message,
        )
        await db.commit()

        await _send_channel_message(str(settings["channel"]), job.request_message)

        job.status = "waiting_dcc"
        job.updated_at = datetime.utcnow()
        _runtime.last_message = (
            f"Download job {job.id} sent to {settings['channel']}; waiting for DCC book transfer"
        )
        await db.commit()
        logger.info(
            "IRC download job %s is now waiting for a DCC offer that matches its request command (bulk_request_id=%s)",
            job.id,
            job.bulk_request_id,
        )


async def _reader_loop(reader: asyncio.StreamReader):
    while True:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=IRC_MAX_TIMEOUT_SECONDS)
            if not raw:
                logger.warning("IRC reader reached EOF; server connection closed")
                _runtime.last_error = "IRC server closed the connection"
                _runtime.last_message = "IRC server closed the connection"
                await _close_connection("IRC server closed the connection")
                return

            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            _runtime.last_message = _summarize_runtime_irc_line(line)
            if _should_log_raw_irc_line(line):
                logger.info("IRC <<< %s", line)
            else:
                logger.debug("IRC <<< %s", line)

            if line.startswith("PING "):
                payload = line.split(" ", 1)[1]
                if _writer is not None:
                    _send_raw_line(_writer, f"PONG {payload}")
                    logger.debug("IRC heartbeat reply sent for server ping")
                continue

            await _handle_server_line(line)

            dcc_offer = _parse_dcc_send_offer(line)
            if dcc_offer is not None:
                await _handle_dcc_offer(dcc_offer)
        except asyncio.CancelledError:
            return
        except asyncio.TimeoutError:
            logger.info("IRC reader idle for %s seconds; keeping session open", IRC_MAX_TIMEOUT_SECONDS)
            _runtime.last_message = f"IRC idle for {IRC_MAX_TIMEOUT_SECONDS} seconds; waiting for new traffic"
        except Exception as exc:
            logger.exception("IRC reader loop failed: %s", exc)
            _runtime.last_error = str(exc)
            await _close_connection(f"IRC reader loop failed: {exc}")
            return


async def _send_channel_message(channel: str, message: str):
    if _writer is None:
        raise RuntimeError("IRC writer is not available for channel message send")
    logger.info("IRC channel command queued for %s: %s", channel, message)
    _send_raw_line(_writer, f"PRIVMSG {channel} :{message}")
    try:
        await _writer.drain()
    except Exception as exc:
        logger.warning("IRC channel command failed during drain: %s", exc)
        raise
    logger.info("IRC channel command sent to %s: %s", channel, message)


async def _join_configured_channel():
    if _writer is None or not _runtime.channel:
        return

    if _runtime.joined_channel:
        return

    settings = await _load_irc_settings()
    channel = str(settings["channel"])
    if not channel:
        return

    _runtime.state = "joining"
    _runtime.last_message = f"Joining IRC channel {channel}"
    if settings["channel_password"]:
        _send_raw_line(_writer, f"JOIN {channel} {settings['channel_password']}")
    else:
        _send_raw_line(_writer, f"JOIN {channel}")
    try:
        await _writer.drain()
    except Exception as exc:
        logger.warning("IRC JOIN command failed during drain: %s", exc)
        raise
    logger.info("IRC JOIN command sent for channel %s", channel)


async def _fail_active_channel_job(error_message: str):
    async with async_session() as db:
        active_search_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.status.in_(["sent", "waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.updated_at.asc())
        )
        active_search_job = active_search_result.scalars().first()
        if active_search_job is not None:
            active_search_job.status = "failed"
            active_search_job.error_message = error_message
            active_search_job.updated_at = datetime.utcnow()
            active_search_job.completed_at = datetime.utcnow()
            await db.commit()
            logger.warning(
                "IRC search job %s failed because the server rejected the channel message: %s",
                active_search_job.id,
                error_message,
            )
            return

        active_download_result = await db.execute(
            select(IrcDownloadJob).where(
                IrcDownloadJob.status.in_(["sent", "waiting_dcc", "downloading"])
            ).order_by(IrcDownloadJob.updated_at.asc())
        )
        active_download_job = active_download_result.scalars().first()
        if active_download_job is not None:
            active_download_job.status = "failed"
            active_download_job.error_message = error_message
            active_download_job.updated_at = datetime.utcnow()
            active_download_job.completed_at = datetime.utcnow()
            await db.commit()
            logger.warning(
                "IRC download job %s failed because the server rejected the channel message: %s",
                active_download_job.id,
                error_message,
            )


async def _fail_active_search_job(error_message: str):
    async with async_session() as db:
        active_search_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.status.in_(["sent", "waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.updated_at.asc())
        )
        active_search_job = active_search_result.scalars().first()
        if active_search_job is None:
            return

        active_search_job.status = "failed"
        active_search_job.error_message = error_message
        active_search_job.updated_at = datetime.utcnow()
        active_search_job.completed_at = datetime.utcnow()
        await db.commit()
        logger.info(
            "IRC search job %s completed early with a server notice: %s",
            active_search_job.id,
            error_message,
        )


def _should_log_raw_irc_line(line: str) -> bool:
    upper_line = line.upper()
    if upper_line.startswith("PING "):
        return False
    if "DCC SEND " in upper_line:
        return False
    if " PRIVMSG " in upper_line:
        return False
    if line.startswith(":") and any(
        token in upper_line for token in (" JOIN ", " PART ", " QUIT ", " KICK ", " NICK ")
    ):
        return False
    return True


def _summarize_runtime_irc_line(line: str) -> str:
    upper_line = line.upper()
    if upper_line.startswith("PING "):
        return "IRC heartbeat received"
    if "DCC SEND " in upper_line:
        return "IRC DCC offer received"
    if " PRIVMSG " in upper_line:
        return "IRC channel activity received"
    return f"IRC traffic received: {line[:180]}"


def _normalize_irc_notice_text(line: str) -> str:
    cleaned = _IRC_COLOR_RE.sub("", line)
    cleaned = _IRC_FORMAT_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _handle_names_reply(line: str):
    if not _runtime.channel or f" {_runtime.channel} " not in line:
        return

    if " :" not in line:
        return

    nick_list = line.split(" :", 1)[1]
    for nick in nick_list.split():
        _track_online_nick(nick)


async def _handle_dcc_offer(offer: dict[str, Any]):
    global _archive_task, _book_download_task

    logger.info(
        "IRC DCC offer received: sender=%s filename=%s host=%s port=%s size=%s",
        offer["sender"],
        offer["filename"],
        offer["host"],
        offer["port"],
        offer["size_bytes"],
    )

    async with async_session() as db:
        active_bulk_search_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.bulk_item_id.is_not(None),
                IrcSearchJob.status.in_(["waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.updated_at.asc())
        )
        active_search_job = active_bulk_search_result.scalars().first()
        if active_search_job is None:
            active_search_result = await db.execute(
                select(IrcSearchJob).where(
                    IrcSearchJob.status.in_(["waiting_dcc", "downloading_results"])
                ).order_by(IrcSearchJob.updated_at.asc())
            )
            active_search_job = active_search_result.scalars().first()

        active_bulk_download_result = await db.execute(
            select(IrcDownloadJob).where(
                IrcDownloadJob.bulk_item_id.is_not(None),
                IrcDownloadJob.status.in_(["waiting_dcc", "downloading"])
            ).order_by(IrcDownloadJob.updated_at.asc())
        )
        active_download_job = active_bulk_download_result.scalars().first()
        if active_download_job is None:
            active_download_result = await db.execute(
                select(IrcDownloadJob).where(
                    IrcDownloadJob.status.in_(["waiting_dcc", "downloading"])
                ).order_by(IrcDownloadJob.updated_at.asc())
            )
            active_download_job = active_download_result.scalars().first()

    if active_search_job is not None and str(offer["filename"]).lower().endswith(".zip"):
        _runtime.active_search_job_id = active_search_job.id
        if result_archive_matches_query(str(offer["filename"]), active_search_job.query_text):
            if _archive_task and not _archive_task.done():
                logger.info(
                    "IRC DCC offer ignored: search archive task already running for job %s",
                    _runtime.active_search_job_id,
                )
                return
            _archive_task = asyncio.create_task(_download_search_result_archive(active_search_job.id, offer))
            return

        logger.info(
            "IRC DCC search offer ignored: filename=%s does not match active search job %s query=%r",
            offer["filename"],
            active_search_job.id,
            active_search_job.query_text,
        )

    if active_download_job is not None:
        _runtime.active_download_job_id = active_download_job.id
        if command_matches_filename(active_download_job.request_message or "", str(offer["filename"])):
            if _book_download_task and not _book_download_task.done():
                logger.info(
                    "IRC DCC book offer ignored: download task already running for job %s",
                    _runtime.active_download_job_id,
                )
                return
            _book_download_task = asyncio.create_task(_download_book_file(active_download_job.id, offer))
            return

        logger.info(
            "IRC DCC book offer ignored: filename=%s does not match active download job %s command=%r",
            offer["filename"],
            active_download_job.id,
            active_download_job.request_message,
        )

    logger.info("IRC DCC offer ignored: no active search or download job matched filename=%s", offer["filename"])


async def _read_dcc_trailing_bytes(
    *,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter | None,
    handle,
    bytes_received: int,
    advertised_size_bytes: int,
    log_prefix: str,
) -> int:
    trailing_bytes = 0

    while trailing_bytes < IRC_DCC_MAX_TRAILING_BYTES:
        try:
            chunk = await asyncio.wait_for(
                reader.read(min(65536, IRC_DCC_MAX_TRAILING_BYTES - trailing_bytes)),
                timeout=IRC_DCC_TRAILING_READ_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            break

        if not chunk:
            break

        handle.write(chunk)
        bytes_received += len(chunk)
        trailing_bytes += len(chunk)

        if writer is not None:
            writer.write(struct.pack("!I", bytes_received & 0xFFFFFFFF))
            await writer.drain()

    if trailing_bytes > 0:
        logger.warning(
            "%s sender transmitted %s extra bytes beyond advertised size=%s; final_size=%s",
            log_prefix,
            trailing_bytes,
            advertised_size_bytes,
            bytes_received,
        )

    return bytes_received


async def _handle_server_line(line: str):
    normalized_line = _normalize_irc_notice_text(line)

    if " NOTICE " in line and "SearchBot" in normalized_line and "returned no matches" in normalized_line.lower():
        _runtime.last_message = "SearchBot reported no matches for the active query"
        logger.warning("IRC SearchBot notice indicates no matches: %s", normalized_line)
        await _fail_active_search_job("Search returned no matches")
        return

    if " 001 " in line:
        logger.info("IRC registration completed; requesting channel join for %s", _runtime.channel)
        await _join_configured_channel()
        return

    if " 353 " in line:
        _handle_names_reply(line)
        return

    if line.startswith(":") and " JOIN " in line:
        prefix = line[1:].split(" ", 1)[0]
        nickname = prefix.split("!", 1)[0]
        channel = line.split(" JOIN ", 1)[1].lstrip(":").strip()
        if channel == _runtime.channel:
            _track_online_nick(nickname)
        if nickname == _runtime.nickname and channel == _runtime.channel:
            _runtime.joined_channel = True
            _runtime.state = "connected"
            _runtime.last_error = None
            _runtime.last_message = f"Joined IRC channel {channel}"
            logger.info("IRC confirmed local nick %s joined %s", nickname, channel)
        return

    if " 366 " in line and _runtime.channel and f" {_runtime.channel} " in line:
        _runtime.joined_channel = True
        _runtime.state = "connected"
        _runtime.last_error = None
        _runtime.last_message = f"Joined IRC channel {_runtime.channel}"
        logger.info("IRC end-of-names confirms join completed for %s", _runtime.channel)
        return

    if line.startswith(":") and " PART " in line:
        prefix = line[1:].split(" ", 1)[0]
        nickname = prefix.split("!", 1)[0]
        channel = line.split(" PART ", 1)[1].split(" ", 1)[0].strip()
        if channel == _runtime.channel:
            _forget_online_nick(nickname)
        return

    if line.startswith(":") and " QUIT " in line:
        prefix = line[1:].split(" ", 1)[0]
        nickname = prefix.split("!", 1)[0]
        _forget_online_nick(nickname)
        return

    if line.startswith(":") and " NICK " in line:
        prefix = line[1:].split(" ", 1)[0]
        old_nickname = prefix.split("!", 1)[0]
        new_nickname = line.split(" NICK ", 1)[1].lstrip(":").strip()
        _replace_online_nick(old_nickname, new_nickname)
        if old_nickname == _runtime.nickname:
            _runtime.nickname = new_nickname
        return

    if line.startswith(":") and " KICK " in line:
        parts = line.split()
        if len(parts) >= 4:
            channel = parts[2]
            kicked_nickname = parts[3]
            if channel == _runtime.channel:
                _forget_online_nick(kicked_nickname)
                if kicked_nickname == _runtime.nickname:
                    _runtime.joined_channel = False
                    _reset_online_nicks()
        return

    if " 451 " in line and "You have not registered" in line:
        logger.warning("IRC server rejected an early command before registration completed: %s", line)
        _runtime.joined_channel = False
        _runtime.state = "registering"
        _runtime.last_message = "Server rejected a pre-registration command; waiting for 001 before rejoining"
        return

    if " 404 " in line and "Cannot send to channel" in line:
        logger.warning("IRC channel send rejected by server: %s", line)
        _runtime.last_error = line
        _runtime.last_message = "Server rejected sending to the configured channel"
        await _fail_active_channel_job(f"IRC server rejected channel message: {line}")
        return

    if " 403 " in line and _runtime.channel and f" {_runtime.channel} " in line:
        logger.warning("IRC channel does not exist or was rejected: %s", line)
        _runtime.last_error = line
        _runtime.last_message = f"Could not join configured channel {_runtime.channel}"
        return

    if " 474 " in line or " 473 " in line or " 475 " in line:
        logger.warning("IRC channel join was rejected: %s", line)
        _runtime.last_error = line
        _runtime.last_message = "IRC server rejected joining the configured channel"
        return


async def _download_search_result_archive(job_id: int, offer: dict[str, Any]):
    filename = str(offer["filename"])
    host = str(offer["host"])
    port = int(offer["port"])
    size_bytes = int(offer["size_bytes"])

    results_dir = DOWNLOADS_DIR / "irc" / "results"
    extract_dir = IRC_STATE_DIR / "extracted_results" / f"job_{job_id}"
    archive_path = results_dir / f"job_{job_id}_{Path(filename).name}"

    logger.info(
        "IRC search job %s starting DCC archive download: filename=%s host=%s port=%s size=%s path=%s",
        job_id,
        filename,
        host,
        port,
        size_bytes,
        archive_path,
    )

    await _update_search_job(job_id, status="downloading_results", error_message=None)
    _runtime.last_message = f"Downloading DCC result archive for search job {job_id}"

    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    bytes_received = 0
    deadline = asyncio.get_running_loop().time() + IRC_DCC_WAIT_TIMEOUT_SECONDS

    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        extract_dir.mkdir(parents=True, exist_ok=True)

        reader, writer = await asyncio.wait_for(
            _open_tcp_connection(
                host,
                port,
                bind_ip=_vpn_bind_ip,
                log_prefix=f"IRC search job {job_id} DCC archive",
            ),
            timeout=IRC_DCC_CONNECT_TIMEOUT_SECONDS,
        )
        logger.info(
            "IRC search job %s connected to DCC sender %s:%s for archive %s",
            job_id,
            host,
            port,
            filename,
        )

        with archive_path.open("wb") as handle:
            while bytes_received < size_bytes:
                remaining = size_bytes - bytes_received
                timeout_remaining = max(0.1, deadline - asyncio.get_running_loop().time())
                if timeout_remaining <= 0:
                    raise TimeoutError(
                        f"DCC archive download timed out after {IRC_DCC_WAIT_TIMEOUT_SECONDS} seconds"
                    )

                chunk = await asyncio.wait_for(
                    reader.read(min(65536, remaining)),
                    timeout=min(IRC_DCC_CHUNK_TIMEOUT_SECONDS, timeout_remaining),
                )
                if not chunk:
                    raise RuntimeError(
                        f"DCC archive download ended early at {bytes_received} of {size_bytes} bytes"
                    )

                handle.write(chunk)
                bytes_received += len(chunk)

                if writer is not None:
                    writer.write(struct.pack("!I", bytes_received & 0xFFFFFFFF))
                    await writer.drain()

            bytes_received = await _read_dcc_trailing_bytes(
                reader=reader,
                writer=writer,
                handle=handle,
                bytes_received=bytes_received,
                advertised_size_bytes=size_bytes,
                log_prefix=f"IRC search job {job_id} DCC archive",
            )

        logger.info(
            "IRC search job %s completed DCC archive download: bytes_received=%s advertised_size=%s filename=%s",
            job_id,
            bytes_received,
            size_bytes,
            filename,
        )

        extracted_text_path, parsed_results = parse_search_results_archive(archive_path, extract_dir)
        logger.info(
            "IRC search job %s parsed archive successfully: archive=%s text=%s results=%s",
            job_id,
            archive_path,
            extracted_text_path,
            len(parsed_results),
        )
        await _store_search_results(job_id, archive_path, extracted_text_path, parsed_results)
        _runtime.last_message = f"Search job {job_id} parsed {len(parsed_results)} result lines"
    except asyncio.CancelledError:
        logger.info("IRC search job %s DCC archive handling cancelled", job_id)
        _runtime.last_message = f"Search job {job_id} was cancelled"
        try:
            if archive_path.exists():
                archive_path.unlink()
        except Exception:
            pass
        raise
    except Exception as exc:
        logger.exception("IRC search job %s failed during DCC archive handling: %s", job_id, exc)
        _runtime.last_error = str(exc)
        _runtime.last_message = f"Search job {job_id} failed during DCC archive handling"
        await _mark_search_job_failed(job_id, str(exc))
        try:
            if archive_path.exists():
                archive_path.unlink()
        except Exception:
            pass
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def _download_book_file(job_id: int, offer: dict[str, Any]):
    filename = Path(str(offer["filename"])).name
    host = str(offer["host"])
    port = int(offer["port"])
    size_bytes = int(offer["size_bytes"])

    downloads_dir = DOWNLOADS_DIR / "irc" / "books"
    download_path = downloads_dir / filename

    logger.info(
        "IRC download job %s starting DCC book download: filename=%s host=%s port=%s size=%s path=%s",
        job_id,
        filename,
        host,
        port,
        size_bytes,
        download_path,
    )

    await _update_download_job(
        job_id,
        status="downloading",
        dcc_filename=filename,
        size_bytes=size_bytes,
        bytes_downloaded=0,
        error_message=None,
    )
    _runtime.last_message = f"Downloading DCC book for job {job_id}"

    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    bytes_received = 0
    download_completed = False
    try:
        downloads_dir.mkdir(parents=True, exist_ok=True)
        reader, writer = await asyncio.wait_for(
            _open_tcp_connection(
                host,
                port,
                bind_ip=_vpn_bind_ip,
                log_prefix=f"IRC download job {job_id} DCC book",
            ),
            timeout=IRC_DCC_CONNECT_TIMEOUT_SECONDS,
        )
        logger.info(
            "IRC download job %s connected to DCC sender %s:%s for file %s",
            job_id,
            host,
            port,
            filename,
        )

        last_progress_update_at = asyncio.get_running_loop().time()
        last_progress_update_bytes = 0
        with download_path.open("wb") as handle:
            while bytes_received < size_bytes:
                remaining = size_bytes - bytes_received
                chunk = await asyncio.wait_for(
                    reader.read(min(65536, remaining)),
                    timeout=IRC_DCC_BOOK_IDLE_TIMEOUT_SECONDS,
                )
                if not chunk:
                    raise RuntimeError(
                        f"DCC book download ended early at {bytes_received} of {size_bytes} bytes"
                    )

                handle.write(chunk)
                bytes_received += len(chunk)

                if writer is not None:
                    writer.write(struct.pack("!I", bytes_received & 0xFFFFFFFF))
                    await writer.drain()

                now = asyncio.get_running_loop().time()
                if (
                    now - last_progress_update_at >= IRC_DCC_PROGRESS_UPDATE_INTERVAL_SECONDS
                    or bytes_received - last_progress_update_bytes >= IRC_DCC_PROGRESS_UPDATE_MIN_BYTES
                    or bytes_received >= size_bytes
                ):
                    await _update_download_job(
                        job_id,
                        status="downloading",
                        dcc_filename=filename,
                        size_bytes=size_bytes,
                        bytes_downloaded=bytes_received,
                        error_message=None,
                    )
                    _runtime.last_message = (
                        f"Downloading DCC book for job {job_id}: {bytes_received}/{size_bytes} bytes"
                    )
                    last_progress_update_at = now
                    last_progress_update_bytes = bytes_received

            bytes_received = await _read_dcc_trailing_bytes(
                reader=reader,
                writer=writer,
                handle=handle,
                bytes_received=bytes_received,
                advertised_size_bytes=size_bytes,
                log_prefix=f"IRC download job {job_id} DCC book",
            )

        logger.info(
            "IRC download job %s completed DCC book download: bytes_received=%s advertised_size=%s filename=%s",
            job_id,
            bytes_received,
            size_bytes,
            filename,
        )
        download_completed = True

        import_path = download_path
        saved_relative_path = str(download_path.relative_to(DOWNLOADS_DIR))

        await _update_download_job(
            job_id,
            status="downloaded",
            dcc_filename=filename,
            size_bytes=size_bytes,
            bytes_downloaded=bytes_received,
            saved_path=saved_relative_path,
            error_message=None,
        )
        _runtime.last_message = f"Download job {job_id} finished downloading; preparing import"

        if download_path.suffix.lower() == ".rar":
            await _update_download_job(
                job_id,
                status="extracting",
                dcc_filename=filename,
                size_bytes=size_bytes,
                bytes_downloaded=bytes_received,
                saved_path=saved_relative_path,
                error_message=None,
            )
            _runtime.last_message = f"Extracting EPUB from archive for download job {job_id}"
            logger.info("IRC download job %s extracting archive to locate EPUB: %s", job_id, download_path)
            import_path = await _extract_epub_from_rar(download_path, job_id)
            saved_relative_path = str(import_path.relative_to(DOWNLOADS_DIR))
            await _update_download_job(
                job_id,
                status="extracted",
                dcc_filename=filename,
                size_bytes=size_bytes,
                bytes_downloaded=bytes_received,
                saved_path=saved_relative_path,
                error_message=None,
            )
            _runtime.last_message = f"Archive extracted for download job {job_id}; EPUB ready for import"
            logger.info(
                "IRC download job %s extracted EPUB from archive: archive=%s epub=%s",
                job_id,
                download_path,
                import_path,
            )

        settings = await _load_irc_settings()
        if settings["auto_move_to_library"]:
            await _update_download_job(
                job_id,
                status="importing",
                dcc_filename=filename,
                size_bytes=size_bytes,
                bytes_downloaded=bytes_received,
                saved_path=saved_relative_path,
                error_message=None,
            )
            _runtime.last_message = f"Importing download job {job_id} into the library"
            moved_path = await _move_download_into_library(import_path, job_id)
            await _update_download_job(
                job_id,
                status="refreshing_library",
                dcc_filename=filename,
                size_bytes=size_bytes,
                bytes_downloaded=bytes_received,
                saved_path=saved_relative_path,
                moved_to_library_path=str(moved_path.relative_to(BOOKS_DIR)),
                error_message=None,
            )
            _runtime.last_message = f"Refreshing library state for download job {job_id}"
            logger.info("IRC download job %s refreshing library state after import: %s", job_id, moved_path)
            await _trigger_library_scan_after_irc_import(moved_path, job_id=job_id)
            await _update_download_job(
                job_id,
                status="moved",
                dcc_filename=filename,
                size_bytes=size_bytes,
                bytes_downloaded=bytes_received,
                saved_path=saved_relative_path,
                moved_to_library_path=str(moved_path.relative_to(BOOKS_DIR)),
                completed_at=datetime.utcnow(),
            )
            logger.info(
                "IRC download job %s moved downloaded file into library: %s",
                job_id,
                moved_path,
            )
            _runtime.last_message = f"Download job {job_id} moved into library"
        else:
            await _update_download_job(
                job_id,
                status="extracted" if import_path != download_path else "downloaded",
                dcc_filename=filename,
                size_bytes=size_bytes,
                bytes_downloaded=bytes_received,
                saved_path=saved_relative_path,
                completed_at=datetime.utcnow(),
                error_message=None,
            )
            logger.info(
                "IRC download job %s completed and left file in downloads directory: %s",
                job_id,
                import_path,
            )
            _runtime.last_message = f"Download job {job_id} completed and stayed in /downloads"
    except asyncio.CancelledError:
        logger.info("IRC download job %s DCC book handling cancelled", job_id)
        _runtime.last_message = f"Download job {job_id} was cancelled"
        try:
            if download_path.exists() and not download_completed:
                download_path.unlink()
        except Exception:
            pass
        raise
    except Exception as exc:
        if isinstance(exc, TimeoutError):
            error_message = (
                f"Timed out waiting for more DCC data while downloading the book for "
                f"{IRC_DCC_BOOK_IDLE_TIMEOUT_SECONDS} seconds"
            )
        else:
            error_message = str(exc).strip() or exc.__class__.__name__
        logger.exception("IRC download job %s failed during DCC book handling: %s", job_id, error_message)
        _runtime.last_error = error_message
        _runtime.last_message = f"Download job {job_id} failed during DCC book handling"
        await _mark_download_job_failed(job_id, error_message)
        try:
            if download_path.exists() and not download_completed:
                download_path.unlink()
        except Exception:
            pass
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def _extract_epub_from_rar(archive_path: Path, job_id: int) -> Path:
    extract_dir = DOWNLOADS_DIR / "irc" / "extracted_books" / f"job_{job_id}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    backend_errors: list[str] = []

    extract_commands: list[tuple[str, list[str]]] = [
        (
            "unar",
            [
                "unar",
                "-f",
                "-o",
                str(extract_dir),
                str(archive_path),
            ],
        ),
        (
            "7z",
            [
                "7z",
                "x",
                "-y",
                f"-o{extract_dir}",
                str(archive_path),
            ],
        ),
    ]

    extracted = False
    for backend_name, command in extract_commands:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except (OSError, TimeoutError) as exc:
            backend_errors.append(f"{backend_name}: {exc}")
            logger.warning(
                "RAR extraction backend failed to start or timed out: backend=%s archive=%s error=%s",
                backend_name,
                archive_path,
                exc,
            )
            continue

        if process.returncode == 0:
            extracted = True
            logger.info("RAR archive extracted successfully using %s: %s", backend_name, archive_path)
            break

        output = (stderr or stdout or b"").decode("utf-8", errors="ignore").strip()
        backend_errors.append(
            f"{backend_name} exited with code {process.returncode}" + (f" ({output[-300:]})" if output else "")
        )
        logger.warning(
            "RAR extraction backend reported an error: backend=%s archive=%s returncode=%s output=%s",
            backend_name,
            archive_path,
            process.returncode,
            output[-300:] if output else "",
        )

    if not extracted:
        raise RuntimeError(
            f"Could not extract RAR archive {archive_path.name}: " + " | ".join(backend_errors)
        )

    epub_candidates = [path for path in extract_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".epub"]
    if not epub_candidates:
        raise RuntimeError(f"No EPUB file found in archive {archive_path.name}")

    epub_candidates.sort(key=lambda path: path.stat().st_size, reverse=True)
    extracted_path = epub_candidates[0]
    if len(epub_candidates) > 1:
        logger.info(
            "RAR archive contains multiple EPUBs; selecting largest extracted file for import: archive=%s selected=%s candidates=%s",
            archive_path,
            extracted_path,
            [str(path.relative_to(extract_dir)) for path in epub_candidates],
        )

    return extracted_path


def _send_raw_line(writer: asyncio.StreamWriter, line: str):
    if line.upper().startswith("PONG "):
        logger.debug("IRC >>> %s", line)
    else:
        logger.info("IRC >>> %s", line)
    writer.write(f"{line}\r\n".encode("utf-8", errors="ignore"))


async def _close_connection(reason: str):
    global _archive_task, _book_download_task, _reader_task, _writer

    if _archive_task and not _archive_task.done():
        _archive_task.cancel()
        try:
            await _archive_task
        except asyncio.CancelledError:
            pass
    _archive_task = None

    if _book_download_task and not _book_download_task.done():
        _book_download_task.cancel()
        try:
            await _book_download_task
        except asyncio.CancelledError:
            pass
    _book_download_task = None

    if _reader_task and not _reader_task.done():
        _reader_task.cancel()
        try:
            await _reader_task
        except asyncio.CancelledError:
            pass
    _reader_task = None

    if _writer is not None:
        _writer.close()
        try:
            await _writer.wait_closed()
        except Exception:
            pass
    _writer = None

    if _runtime.connected or _runtime.joined_channel:
        logger.info("IRC connection closed: %s", reason)

    _runtime.connected = False
    _runtime.joined_channel = False
    _reset_online_nicks()


async def _expire_stale_search_jobs():
    async with async_session() as db:
        result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.status.in_(["waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.updated_at.asc())
        )
        jobs = result.scalars().all()

        now = datetime.utcnow()
        for job in jobs:
            age_seconds = (now - job.updated_at).total_seconds()
            if age_seconds <= IRC_DCC_WAIT_TIMEOUT_SECONDS:
                continue

            job.status = "failed"
            job.error_message = (
                f"Timed out after {IRC_DCC_WAIT_TIMEOUT_SECONDS} seconds waiting for the DCC result archive"
            )
            job.updated_at = now
            job.completed_at = now
            logger.warning(
                "IRC search job %s expired after %.1f seconds in status=%s query=%r",
                job.id,
                age_seconds,
                job.status,
                job.query_text,
            )
        await db.commit()


async def _expire_stale_download_jobs():
    async with async_session() as db:
        result = await db.execute(
            select(IrcDownloadJob).where(
                IrcDownloadJob.status.in_(["waiting_dcc", "downloading"])
            ).order_by(IrcDownloadJob.updated_at.asc())
        )
        jobs = result.scalars().all()

        now = datetime.utcnow()
        for job in jobs:
            age_seconds = (now - job.updated_at).total_seconds()
            timeout_seconds = (
                IRC_DCC_BOOK_IDLE_TIMEOUT_SECONDS
                if job.status == "downloading"
                else IRC_DCC_WAIT_TIMEOUT_SECONDS
            )
            if age_seconds <= timeout_seconds:
                continue

            previous_status = job.status
            job.status = "failed"
            job.error_message = (
                f"Timed out after {timeout_seconds} seconds waiting for the DCC book transfer"
            )
            job.updated_at = now
            job.completed_at = now
            logger.warning(
                "IRC download job %s expired after %.1f seconds in status=%s command=%r",
                job.id,
                age_seconds,
                previous_status,
                job.request_message,
            )
        await db.commit()


def _parse_dcc_send_offer(line: str) -> dict[str, Any] | None:
    if "DCC SEND " not in line:
        return None

    sender = None
    if line.startswith(":") and "!" in line:
        sender = line[1:].split("!", 1)[0]

    marker = "\x01DCC SEND "
    start_index = line.find(marker)
    if start_index == -1:
        return None

    payload = line[start_index + len(marker):]
    payload = payload.rstrip("\x01").strip()
    if not payload:
        return None

    filename = None
    remainder = ""
    if payload.startswith('"'):
        end_quote = payload.find('"', 1)
        if end_quote == -1:
            return None
        filename = payload[1:end_quote]
        remainder = payload[end_quote + 1:].strip()
    else:
        parts = payload.rsplit(" ", 3)
        if len(parts) != 4:
            return None
        filename, host_value, port_value, size_value = parts
        remainder = f"{host_value} {port_value} {size_value}"

    pieces = remainder.split()
    if len(pieces) < 3:
        return None

    host_value, port_value, size_value = pieces[:3]
    try:
        return {
            "sender": sender,
            "filename": filename,
            "host": _decode_dcc_host(host_value),
            "port": int(port_value),
            "size_bytes": int(size_value),
        }
    except Exception:
        logger.warning("IRC DCC offer could not be parsed: %s", line)
        return None


def _decode_dcc_host(value: str) -> str:
    if "." in value:
        return value
    return inet_ntoa(struct.pack("!I", int(value)))


async def _update_search_job(job_id: int, **updates):
    async with async_session() as db:
        result = await db.execute(select(IrcSearchJob).where(IrcSearchJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return

        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = datetime.utcnow()
        await db.commit()


async def _mark_search_job_failed(job_id: int, error_message: str):
    async with async_session() as db:
        result = await db.execute(select(IrcSearchJob).where(IrcSearchJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return

        job.status = "failed"
        job.error_message = error_message
        job.updated_at = datetime.utcnow()
        job.completed_at = datetime.utcnow()
        await db.commit()


async def _update_download_job(job_id: int, **updates):
    async with async_session() as db:
        result = await db.execute(select(IrcDownloadJob).where(IrcDownloadJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return

        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = datetime.utcnow()
        await db.commit()


async def _mark_download_job_failed(job_id: int, error_message: str):
    async with async_session() as db:
        result = await db.execute(select(IrcDownloadJob).where(IrcDownloadJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return

        job.status = "failed"
        job.error_message = error_message
        job.updated_at = datetime.utcnow()
        job.completed_at = datetime.utcnow()
        await db.commit()


async def _store_search_results(
    job_id: int,
    archive_path: Path,
    text_path: Path,
    parsed_results: list[dict[str, Any]],
):
    async with async_session() as db:
        result = await db.execute(select(IrcSearchJob).where(IrcSearchJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return

        await db.execute(delete(IrcSearchResult).where(IrcSearchResult.search_job_id == job_id))

        created_results: list[IrcSearchResult] = []
        for index, row in enumerate(parsed_results, start=1):
            result_row = IrcSearchResult(
                search_job_id=job_id,
                result_index=index,
                raw_line=str(row.get("raw_line") or ""),
                bot_name=row.get("bot_name"),
                display_name=str(row.get("display_name") or ""),
                normalized_title=row.get("normalized_title"),
                normalized_author=row.get("normalized_author"),
                file_format=row.get("file_format"),
                file_size_text=row.get("file_size_text"),
                download_command=str(row.get("download_command") or ""),
                selected=False,
            )
            created_results.append(result_row)
            db.add(result_row)

        logger.info(
            "IRC search job %s stored parsed results: bulk_request_id=%s result_count=%s auto_download=%s",
            job_id,
            job.bulk_request_id,
            len(created_results),
            job.auto_download,
        )

        if job.auto_download and len(created_results) == 1 and created_results[0].download_command:
            selected_result = created_results[0]
            selected_result.selected = True
            db.add(IrcDownloadJob(
                book_id=job.book_id,
                search_job_id=job_id,
                search_result=selected_result,
                status="queued",
                bulk_request_id=job.bulk_request_id,
                request_message=selected_result.download_command,
                dcc_filename=selected_result.display_name,
            ))
            logger.info(
                "IRC search job %s auto-queued download job for single parsed result: bulk_request_id=%s result=%s",
                job_id,
                job.bulk_request_id,
                selected_result.display_name,
            )
        elif job.auto_download and len(created_results) != 1:
            logger.info(
                "IRC search job %s did not auto-queue a download: bulk_request_id=%s reason=result_count_%s",
                job_id,
                job.bulk_request_id,
                len(created_results),
            )
        elif job.auto_download and len(created_results) == 1 and not created_results[0].download_command:
            logger.warning(
                "IRC search job %s did not auto-queue a download: bulk_request_id=%s reason=missing_download_command",
                job_id,
                job.bulk_request_id,
            )

        job.result_archive_path = str(archive_path.relative_to(DOWNLOADS_DIR))
        job.result_text_path = str(text_path)
        job.status = "results_ready"
        job.error_message = None
        job.updated_at = datetime.utcnow()
        job.completed_at = datetime.utcnow()
        await db.commit()


async def _move_download_into_library(download_path: Path, job_id: int) -> Path:
    target_path = await _build_library_target_path(download_path, job_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        stem = target_path.stem
        suffix = target_path.suffix
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        target_path = target_path.with_name(f"{stem}_{timestamp}{suffix}")

    logger.info("Moving IRC download into library: source=%s target=%s", download_path, target_path)
    shutil.move(str(download_path), str(target_path))
    return target_path


async def _build_library_target_path(download_path: Path, job_id: int) -> Path:
    author_name, book_name, linked_file_path, mapped_author_dir_name = await _resolve_import_names(download_path, job_id)
    author_dir_name = _resolve_existing_author_dir_name(author_name, linked_file_path, mapped_author_dir_name)
    book_dir_name = _resolve_existing_book_dir_name(author_dir_name, book_name, linked_file_path)

    target_dir = BOOKS_DIR / author_dir_name / book_dir_name
    logger.info(
        "Resolved IRC library import destination: job_id=%s author=%r book=%r target_dir=%s",
        job_id,
        author_dir_name,
        book_dir_name,
        target_dir,
    )
    return target_dir / download_path.name


async def _resolve_import_names(download_path: Path, job_id: int) -> tuple[str, str, str | None, str | None]:
    author_name: str | None = None
    book_name: str | None = None
    linked_file_path: str | None = None
    mapped_author_dir_name: str | None = None

    async with async_session() as db:
        result = await db.execute(
            select(IrcDownloadJob)
            .options(selectinload(IrcDownloadJob.search_result))
            .where(IrcDownloadJob.id == job_id)
        )
        job = result.scalar_one_or_none()

        if job and job.book_id:
            book_result = await db.execute(
                select(Book).options(selectinload(Book.author), selectinload(Book.files)).where(Book.id == job.book_id)
            )
            linked_book = book_result.scalar_one_or_none()
            if linked_book:
                author_name = linked_book.author.name if linked_book.author else None
                book_name = linked_book.title
                if linked_book.files:
                    linked_file_path = linked_book.files[0].file_path
                logger.info(
                    "IRC import destination using linked library book: job_id=%s author=%r title=%r linked_file=%r",
                    job_id,
                    author_name,
                    book_name,
                    linked_file_path,
                )

        if author_name and not linked_file_path:
            author_result = await db.execute(
                select(Author)
                .options(selectinload(Author.author_directories))
                .limit(1)
                .where(Author.name == author_name)
            )
            mapped_author = author_result.scalar_one_or_none()
            if mapped_author and mapped_author.author_directories:
                primary_dir = next(
                    (directory for directory in mapped_author.author_directories if directory.is_primary),
                    mapped_author.author_directories[0],
                )
                mapped_author_dir_name = primary_dir.dir_path
                logger.info(
                    "IRC import destination using mapped author directory: job_id=%s author=%r dir=%r",
                    job_id,
                    author_name,
                    mapped_author_dir_name,
                )

        if job and job.search_result:
            if not author_name and job.search_result.normalized_author:
                author_name = job.search_result.normalized_author
            if not book_name:
                book_name = (
                    job.search_result.normalized_title
                    or job.search_result.display_name
                    or job.dcc_filename
                )

    epub_meta = parse_epub_opf(download_path) if download_path.suffix.lower() == ".epub" else None
    if epub_meta:
        if not author_name and epub_meta.author:
            author_name = epub_meta.author.strip()
        if not book_name and epub_meta.title:
            book_name = epub_meta.title.strip()
        logger.info(
            "IRC import EPUB metadata probe: job_id=%s epub_author=%r epub_title=%r",
            job_id,
            epub_meta.author,
            epub_meta.title,
        )

    if not author_name or not book_name:
        guessed_author, guessed_title = _guess_author_title_from_filename(download_path.name)
        author_name = author_name or guessed_author
        book_name = book_name or guessed_title
        logger.info(
            "IRC import filename fallback: job_id=%s guessed_author=%r guessed_title=%r filename=%r",
            job_id,
            guessed_author,
            guessed_title,
            download_path.name,
        )

    return author_name or "IRC Imports", book_name or download_path.stem, linked_file_path, mapped_author_dir_name


def _guess_author_title_from_filename(filename: str) -> tuple[str | None, str | None]:
    stem = Path(filename).stem.strip()
    if not stem:
        return None, None

    if " - " in stem:
        parts = [part.strip() for part in stem.split(" - ") if part.strip()]
        if len(parts) == 2:
            return parts[1], parts[0]
        if len(parts) >= 3:
            return parts[0], " - ".join(parts[1:])

    return None, stem


def _sanitize_library_component(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value).strip()
    sanitized = re.sub(r"\s+", " ", sanitized).rstrip(".")
    return sanitized or "Unknown"


def _resolve_existing_author_dir_name(
    author_name: str | None,
    linked_file_path: str | None,
    mapped_author_dir_name: str | None = None,
) -> str:
    if linked_file_path:
        parts = Path(linked_file_path).parts
        if parts:
            return parts[0]

    if mapped_author_dir_name:
        return mapped_author_dir_name

    normalized_author = _normalize_author_key(author_name or "")
    if normalized_author and BOOKS_DIR.exists():
        for author_dir in sorted(BOOKS_DIR.iterdir()):
            if not author_dir.is_dir() or author_dir.name.startswith("."):
                continue
            if _normalize_author_key(author_dir.name) == normalized_author:
                return author_dir.name

    return _sanitize_library_component(author_name or "IRC Imports")


def _resolve_existing_book_dir_name(author_dir_name: str, book_name: str | None, linked_file_path: str | None) -> str:
    if linked_file_path:
        parts = Path(linked_file_path).parts
        if len(parts) >= 3:
            return parts[1]

    normalized_book = normalize_title(book_name or "")
    author_dir = BOOKS_DIR / author_dir_name
    if normalized_book and author_dir.exists():
        for book_dir in sorted(author_dir.iterdir()):
            if not book_dir.is_dir() or book_dir.name.startswith("."):
                continue
            if normalize_title(book_dir.name) == normalized_book:
                return book_dir.name

    return _sanitize_library_component(book_name or "Unknown")


def _normalize_author_key(author_name: str) -> str:
    cleaned = author_name.strip()
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        if len(parts) == 2:
            cleaned = f"{parts[1]} {parts[0]}"
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


async def _trigger_library_scan_after_irc_import(moved_path: Path, job_id: int | None = None):
    try:
        from backend.app.services.library_sync import refresh_imported_library_file, run_full_sync, scan_status
    except Exception as exc:
        logger.warning("Could not import library sync after IRC move for %s: %s", moved_path, exc)
        return

    if scan_status.status == "scanning":
        logger.info(
            "IRC import moved file into library but skipped auto-scan because a scan is already running: %s",
            moved_path,
        )
        return

    expected_book_id = await _get_download_job_book_id(job_id) if job_id is not None else None
    logger.info(
        "Triggering targeted refresh after IRC import: path=%s job_id=%s expected_book_id=%s",
        moved_path,
        job_id,
        expected_book_id,
    )
    try:
        imported_and_matched = await refresh_imported_library_file(
            moved_path,
            expected_book_id=expected_book_id,
        )
    except Exception as exc:
        logger.warning("Targeted refresh after IRC import failed for %s: %s", moved_path, exc)
        imported_and_matched = False

    if imported_and_matched:
        logger.info("Targeted IRC import refresh marked the book as owned without a full library scan: %s", moved_path)
        return

    logger.info("Targeted IRC import refresh did not fully resolve ownership; falling back to library scan: %s", moved_path)
    asyncio.create_task(run_full_sync(force=False))


async def _get_download_job_book_id(job_id: int) -> int | None:
    async with async_session() as db:
        result = await db.execute(select(IrcDownloadJob.book_id).where(IrcDownloadJob.id == job_id))
        return result.scalar_one_or_none()


async def _load_irc_settings() -> dict[str, object]:
    from backend.app.services.vpn_manager import normalize_pia_region

    async with async_session() as db:
        result = await db.execute(select(Setting).where(Setting.key.like("irc_%")))
        settings = {row.key: row.value for row in result.scalars().all()}

    return {
        "enabled": settings.get("irc_enabled", "false").lower() == "true",
        "server": settings.get("irc_server", ""),
        "port": int(settings.get("irc_port", "6697")),
        "use_tls": settings.get("irc_use_tls", "true").lower() == "true",
        "nickname": settings.get("irc_nickname", ""),
        "username": settings.get("irc_username", ""),
        "real_name": settings.get("irc_real_name", ""),
        "channel": settings.get("irc_channel", ""),
        "channel_password": settings.get("irc_channel_password", ""),
        "vpn_enabled": settings.get("irc_vpn_enabled", "false").lower() == "true",
        "vpn_region": normalize_pia_region(settings.get("irc_vpn_region", "Netherlands")),
        "vpn_username": settings.get("irc_vpn_username", ""),
        "vpn_password": settings.get("irc_vpn_password", ""),
        "auto_move_to_library": settings.get("irc_auto_move_to_library", "true").lower() == "true",
    }


async def _open_tcp_connection(
    host: str,
    port: int,
    *,
    ssl_context: ssl.SSLContext | None = None,
    server_hostname: str | None = None,
    bind_ip: str | None = None,
    log_prefix: str = "TCP connection",
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    if bind_ip:
        logger.info("%s opening TCP connection to %s:%s bound to VPN IP %s", log_prefix, host, port, bind_ip)
        local_addr = (bind_ip, 0)
    else:
        logger.info("%s opening direct TCP connection to %s:%s", log_prefix, host, port)
        local_addr = None

    return await asyncio.open_connection(
        host,
        port,
        ssl=ssl_context,
        server_hostname=server_hostname,
        local_addr=local_addr,
    )


async def _get_queue_counts() -> tuple[int, int]:
    async with async_session() as db:
        search_result = await db.execute(
            select(func.count(IrcSearchJob.id)).where(IrcSearchJob.status.in_(["queued", "sent", "waiting_dcc", "downloading_results"]))
        )
        download_result = await db.execute(
            select(func.count(IrcDownloadJob.id)).where(
                IrcDownloadJob.status.in_([
                    "queued",
                    "sent",
                    "waiting_dcc",
                    "downloading",
                    "extracting",
                    "importing",
                    "refreshing_library",
                ])
            )
        )
        return search_result.scalar() or 0, download_result.scalar() or 0
