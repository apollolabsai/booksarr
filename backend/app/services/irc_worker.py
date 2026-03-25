import asyncio
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
from backend.app.models import Book, IrcDownloadJob, IrcSearchJob, IrcSearchResult, Setting
from backend.app.services.irc_parser import (
    build_expected_result_filename,
    build_search_command,
    command_matches_filename,
    normalize_query_text,
    parse_search_results_archive,
    result_archive_matches_query,
)
from backend.app.utils.opf_parser import parse_epub_opf

logger = logging.getLogger("booksarr.irc")

IRC_MAX_TIMEOUT_SECONDS = 60
IRC_CONNECT_TIMEOUT_SECONDS = 15
IRC_DCC_CONNECT_TIMEOUT_SECONDS = 15
IRC_DCC_WAIT_TIMEOUT_SECONDS = 60
IRC_DCC_CHUNK_TIMEOUT_SECONDS = 10

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


def get_runtime_status() -> IrcRuntimeState:
    return IrcRuntimeState(**asdict(_runtime))


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
    _runtime.state = "stopped"
    await _close_connection("Worker shutdown")
    logger.info("IRC worker stopped")


async def request_connect():
    _runtime.desired_connection = True
    _runtime.last_message = "Connection requested from UI"
    logger.info("IRC connection requested")


async def request_disconnect():
    _runtime.desired_connection = False
    await _close_connection("Disconnect requested from UI")
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
                if _runtime.state != "idle":
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

            if not _runtime.connected:
                await _attempt_connection(settings)
            else:
                await _expire_stale_search_jobs()
                await _expire_stale_download_jobs()
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
    global _reader_task, _writer
    server = str(settings["server"])
    port = int(settings["port"])
    use_tls = bool(settings["use_tls"])
    nickname = str(settings["nickname"])
    username = str(settings["username"] or settings["nickname"])
    real_name = str(settings["real_name"] or settings["nickname"])
    channel = str(settings["channel"])

    _runtime.state = "connecting"
    _runtime.last_message = f"Connecting to {server}:{port}"
    logger.info(
        "IRC connect attempt: server=%s port=%s tls=%s nick=%s channel=%s",
        server, port, use_tls, nickname, channel,
    )

    try:
        ssl_context = ssl.create_default_context() if use_tls else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port, ssl=ssl_context),
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
        _runtime.state = "connect_failed"
        _runtime.last_error = str(exc)
        _runtime.last_message = f"Connection failed: {exc}"
        logger.warning("IRC connection failed: %s", exc)


async def _process_next_search_job(settings: dict[str, object]):
    if not _runtime.connected or not _runtime.joined_channel or _writer is None:
        return

    async with async_session() as db:
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
            "IRC search job %s dispatching: query='%s' expected_result='%s'",
            job.id,
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
            "IRC search job %s is now waiting for a DCC result archive that matches query '%s'",
            job.id,
            job.query_text,
        )


async def _process_next_download_job(settings: dict[str, object]):
    if not _runtime.connected or not _runtime.joined_channel or _writer is None:
        return

    async with async_session() as db:
        active_search_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.status.in_(["sent", "waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.created_at.asc())
        )
        active_search_job = active_search_result.scalars().first()
        if active_search_job is not None:
            return

        active_download_result = await db.execute(
            select(IrcDownloadJob).where(
                IrcDownloadJob.status.in_(["sent", "waiting_dcc", "downloading"])
            ).order_by(IrcDownloadJob.created_at.asc())
        )
        active_download_job = active_download_result.scalars().first()
        if active_download_job is not None:
            _runtime.active_download_job_id = active_download_job.id
            _runtime.last_message = (
                f"Download job {active_download_job.id} waiting for DCC file offer"
            )
            return

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
            "IRC download job %s dispatching: search_job_id=%s search_result_id=%s command=%r",
            job.id,
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
            "IRC download job %s is now waiting for a DCC offer that matches its request command",
            job.id,
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
            _runtime.last_message = f"IRC traffic received: {line[:180]}"
            logger.info("IRC <<< %s", line)

            if line.startswith("PING "):
                payload = line.split(" ", 1)[1]
                if _writer is not None:
                    _send_raw_line(_writer, f"PONG {payload}")
                    logger.info("IRC heartbeat reply sent for server ping")
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
        active_search_result = await db.execute(
            select(IrcSearchJob).where(
                IrcSearchJob.status.in_(["waiting_dcc", "downloading_results"])
            ).order_by(IrcSearchJob.updated_at.asc())
        )
        active_search_job = active_search_result.scalars().first()

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


async def _handle_server_line(line: str):
    if " 001 " in line:
        logger.info("IRC registration completed; requesting channel join for %s", _runtime.channel)
        await _join_configured_channel()
        return

    if line.startswith(":") and " JOIN " in line:
        prefix = line[1:].split(" ", 1)[0]
        nickname = prefix.split("!", 1)[0]
        channel = line.split(" JOIN ", 1)[1].lstrip(":").strip()
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
            asyncio.open_connection(host, port),
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

        logger.info(
            "IRC search job %s completed DCC archive download: bytes_received=%s filename=%s",
            job_id,
            bytes_received,
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

    await _update_download_job(job_id, status="downloading", error_message=None)
    _runtime.last_message = f"Downloading DCC book for job {job_id}"

    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    bytes_received = 0
    deadline = asyncio.get_running_loop().time() + IRC_DCC_WAIT_TIMEOUT_SECONDS

    try:
        downloads_dir.mkdir(parents=True, exist_ok=True)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=IRC_DCC_CONNECT_TIMEOUT_SECONDS,
        )
        logger.info(
            "IRC download job %s connected to DCC sender %s:%s for file %s",
            job_id,
            host,
            port,
            filename,
        )

        with download_path.open("wb") as handle:
            while bytes_received < size_bytes:
                remaining = size_bytes - bytes_received
                timeout_remaining = max(0.1, deadline - asyncio.get_running_loop().time())
                if timeout_remaining <= 0:
                    raise TimeoutError(
                        f"DCC book download timed out after {IRC_DCC_WAIT_TIMEOUT_SECONDS} seconds"
                    )

                chunk = await asyncio.wait_for(
                    reader.read(min(65536, remaining)),
                    timeout=min(IRC_DCC_CHUNK_TIMEOUT_SECONDS, timeout_remaining),
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

        logger.info(
            "IRC download job %s completed DCC book download: bytes_received=%s filename=%s",
            job_id,
            bytes_received,
            filename,
        )

        await _update_download_job(
            job_id,
            status="downloaded",
            dcc_filename=filename,
            saved_path=str(download_path.relative_to(DOWNLOADS_DIR)),
            error_message=None,
        )

        settings = await _load_irc_settings()
        if settings["auto_move_to_library"]:
            moved_path = await _move_download_into_library(download_path, job_id)
            await _update_download_job(
                job_id,
                status="moved",
                dcc_filename=filename,
                saved_path=str(download_path.relative_to(DOWNLOADS_DIR)),
                moved_to_library_path=str(moved_path.relative_to(BOOKS_DIR)),
                completed_at=datetime.utcnow(),
            )
            logger.info(
                "IRC download job %s moved downloaded file into library: %s",
                job_id,
                moved_path,
            )
            _runtime.last_message = f"Download job {job_id} moved into library"
            await _trigger_library_scan_after_irc_import(moved_path)
        else:
            await _update_download_job(job_id, completed_at=datetime.utcnow())
            logger.info(
                "IRC download job %s completed and left file in downloads directory: %s",
                job_id,
                download_path,
            )
            _runtime.last_message = f"Download job {job_id} completed and stayed in /downloads"
    except Exception as exc:
        logger.exception("IRC download job %s failed during DCC book handling: %s", job_id, exc)
        _runtime.last_error = str(exc)
        _runtime.last_message = f"Download job {job_id} failed during DCC book handling"
        await _mark_download_job_failed(job_id, str(exc))
        try:
            if download_path.exists():
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


def _send_raw_line(writer: asyncio.StreamWriter, line: str):
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
            if age_seconds <= IRC_DCC_WAIT_TIMEOUT_SECONDS:
                continue

            previous_status = job.status
            job.status = "failed"
            job.error_message = (
                f"Timed out after {IRC_DCC_WAIT_TIMEOUT_SECONDS} seconds waiting for the DCC book transfer"
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

        for index, row in enumerate(parsed_results, start=1):
            db.add(IrcSearchResult(
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
            ))

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
    author_name, book_name = await _resolve_import_names(download_path, job_id)
    author_dir_name = _sanitize_library_component(author_name or "IRC Imports")
    book_dir_name = _sanitize_library_component(book_name or download_path.stem)

    target_dir = BOOKS_DIR / author_dir_name / book_dir_name
    logger.info(
        "Resolved IRC library import destination: job_id=%s author=%r book=%r target_dir=%s",
        job_id,
        author_dir_name,
        book_dir_name,
        target_dir,
    )
    return target_dir / download_path.name


async def _resolve_import_names(download_path: Path, job_id: int) -> tuple[str, str]:
    author_name: str | None = None
    book_name: str | None = None

    async with async_session() as db:
        result = await db.execute(
            select(IrcDownloadJob)
            .options(selectinload(IrcDownloadJob.search_result))
            .where(IrcDownloadJob.id == job_id)
        )
        job = result.scalar_one_or_none()

        if job and job.book_id:
            book_result = await db.execute(
                select(Book).options(selectinload(Book.author)).where(Book.id == job.book_id)
            )
            linked_book = book_result.scalar_one_or_none()
            if linked_book:
                author_name = linked_book.author.name if linked_book.author else None
                book_name = linked_book.title
                logger.info(
                    "IRC import destination using linked library book: job_id=%s author=%r title=%r",
                    job_id,
                    author_name,
                    book_name,
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

    return author_name or "IRC Imports", book_name or download_path.stem


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


async def _trigger_library_scan_after_irc_import(moved_path: Path):
    try:
        from backend.app.services.library_sync import run_full_sync, scan_status
    except Exception as exc:
        logger.warning("Could not import library sync after IRC move for %s: %s", moved_path, exc)
        return

    if scan_status.status == "scanning":
        logger.info(
            "IRC import moved file into library but skipped auto-scan because a scan is already running: %s",
            moved_path,
        )
        return

    logger.info("Triggering library scan after IRC import: %s", moved_path)
    asyncio.create_task(run_full_sync(force=False))


async def _load_irc_settings() -> dict[str, object]:
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
        "auto_move_to_library": settings.get("irc_auto_move_to_library", "true").lower() == "true",
    }


async def _get_queue_counts() -> tuple[int, int]:
    async with async_session() as db:
        search_result = await db.execute(
            select(func.count(IrcSearchJob.id)).where(IrcSearchJob.status.in_(["queued", "sent", "waiting_dcc", "downloading_results"]))
        )
        download_result = await db.execute(
            select(func.count(IrcDownloadJob.id)).where(IrcDownloadJob.status.in_(["queued", "sent", "waiting_dcc", "downloading"]))
        )
        return search_result.scalar() or 0, download_result.scalar() or 0
