import pytest

from backend.app.routers import irc as irc_router
from backend.app.services import irc_worker


@pytest.mark.asyncio
async def test_start_irc_worker_does_not_start_task_when_disabled(monkeypatch):
    async def fake_load_enabled():
        return False

    monkeypatch.setattr(irc_worker, "_worker_task", None)
    monkeypatch.setattr(irc_worker, "_stop_event", None)
    monkeypatch.setattr(irc_worker, "_load_irc_enabled", fake_load_enabled)

    started = await irc_worker.start_irc_worker()

    assert started is False
    assert irc_worker._worker_task is None
    assert irc_worker.get_runtime_status().state == "disabled"


@pytest.mark.asyncio
async def test_worker_loop_does_not_read_queue_counts_when_disabled(monkeypatch):
    stop_event = irc_worker.asyncio.Event()

    async def fake_load_settings():
        return {
            "enabled": False,
            "server": "",
            "port": 6697,
            "use_tls": True,
            "nickname": "",
            "username": "",
            "real_name": "",
            "channel": "",
            "channel_password": "",
            "vpn_enabled": False,
            "vpn_region": "Netherlands",
            "vpn_username": "",
            "vpn_password": "",
            "auto_move_to_library": True,
        }

    async def fake_get_queue_counts():
        raise AssertionError("disabled IRC worker should not read queue counts")

    async def fake_close_connection(_reason: str):
        return None

    async def fake_sleep(_seconds: float):
        stop_event.set()

    monkeypatch.setattr(irc_worker, "_stop_event", stop_event)
    monkeypatch.setattr(irc_worker, "_load_irc_settings", fake_load_settings)
    monkeypatch.setattr(irc_worker, "_get_queue_counts", fake_get_queue_counts)
    monkeypatch.setattr(irc_worker, "_close_connection", fake_close_connection)
    monkeypatch.setattr(irc_worker.asyncio, "sleep", fake_sleep)

    await irc_worker._worker_loop()


@pytest.mark.asyncio
async def test_disabled_status_does_not_read_queue_counts(monkeypatch):
    runtime = irc_worker.IrcRuntimeState(enabled=False, state="disabled")

    async def fake_get_queue_counts(_db):
        raise AssertionError("disabled IRC status should not read queue counts")

    monkeypatch.setattr(irc_router, "get_runtime_status", lambda: runtime)
    monkeypatch.setattr(irc_router, "_get_queue_counts", fake_get_queue_counts)

    status = await irc_router.get_irc_status(db=None)

    assert status.enabled is False
    assert status.queued_search_jobs == 0
    assert status.queued_download_jobs == 0
