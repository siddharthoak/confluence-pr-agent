from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from confluence_pr_agent.models import PipelineResult
from confluence_pr_agent.pipeline import poller


def _fake_deps():
    deps = AsyncMock()
    deps.confluence.search_page_ids.return_value = ["111", "222"]
    return deps


async def test_poll_once_runs_the_pipeline_for_every_discovered_page(settings, monkeypatch):
    settings.confluence_space_key = "SD"
    settings.confluence_allowed_labels = "brd"
    deps = _fake_deps()
    monkeypatch.setattr(poller, "build_deps", lambda s: deps)

    run_calls = []

    async def _fake_run_pipeline(page_id, deps=None):
        run_calls.append(page_id)
        return PipelineResult(status="opened_pr")

    monkeypatch.setattr(poller, "run_pipeline", _fake_run_pipeline)

    results = await poller.poll_once(settings)

    deps.confluence.search_page_ids.assert_awaited_once_with("SD", ["brd"])
    assert run_calls == ["111", "222"]
    assert len(results) == 2
    deps.confluence.aclose.assert_awaited_once()
    deps.github.aclose.assert_awaited_once()
    deps.email_client.aclose.assert_awaited_once()
    deps.jira.aclose.assert_awaited_once()


async def test_poll_once_keeps_going_past_a_single_page_failure(settings, monkeypatch):
    deps = _fake_deps()
    monkeypatch.setattr(poller, "build_deps", lambda s: deps)

    async def _fake_run_pipeline(page_id, deps=None):
        if page_id == "111":
            raise RuntimeError("boom")
        return PipelineResult(status="opened_pr")

    monkeypatch.setattr(poller, "run_pipeline", _fake_run_pipeline)

    results = await poller.poll_once(settings)

    assert len(results) == 1  # only the second page's result survives
    deps.confluence.aclose.assert_awaited_once()


async def test_poll_once_skips_a_concurrent_call_while_one_is_already_running(settings, monkeypatch):
    deps = _fake_deps()
    monkeypatch.setattr(poller, "build_deps", lambda s: deps)

    started = asyncio.Event()
    release = asyncio.Event()

    async def _fake_run_pipeline(page_id, deps=None):
        started.set()
        await release.wait()
        return PipelineResult(status="opened_pr")

    monkeypatch.setattr(poller, "run_pipeline", _fake_run_pipeline)

    first = asyncio.create_task(poller.poll_once(settings))
    await started.wait()

    # A second call while the first is still mid-flight is a safe no-op,
    # not a second concurrent cycle over the same pages.
    second_result = await poller.poll_once(settings)
    assert second_result == []

    release.set()
    first_result = await first
    assert len(first_result) == 2


async def test_poll_scan_loop_polls_only_enabled_users(tmp_path, monkeypatch):
    from confluence_pr_agent.config import get_process_config, get_settings

    real_sleep = asyncio.sleep  # captured before asyncio.sleep gets monkeypatched below

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_process_config.cache_clear()
    get_settings.cache_clear()

    process = get_process_config()
    process.user_env_path("alice").write_text(
        "CONFLUENCE_POLL_ENABLED=true\nCONFLUENCE_POLL_INTERVAL_SECONDS=300\n"
    )
    process.user_env_path("bob").write_text("CONFLUENCE_POLL_ENABLED=false\n")

    polled_data_dirs = []

    async def _fake_poll_once(settings):
        polled_data_dirs.append(settings.data_dir)
        return []

    async def _fake_sleep(seconds):
        assert seconds == poller.POLL_SCAN_TICK_SECONDS
        # asyncio.sleep is globally patched for the duration of this test,
        # so this has to go through the real one (captured above) to
        # actually yield to the loop -- otherwise the create_task(...) this
        # tick scheduled for alice never gets a turn to run before we
        # cancel the scan loop below.
        await real_sleep(0)
        raise asyncio.CancelledError()

    monkeypatch.setattr(poller, "poll_once", _fake_poll_once)
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await poller.poll_scan_loop()

    assert len(polled_data_dirs) == 1
    assert "alice" in polled_data_dirs[0]

    get_process_config.cache_clear()
    get_settings.cache_clear()


async def test_poll_scan_loop_respects_each_users_own_interval(tmp_path, monkeypatch):
    from confluence_pr_agent.config import get_process_config, get_settings

    real_sleep = asyncio.sleep

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_process_config.cache_clear()
    get_settings.cache_clear()

    process = get_process_config()
    # A normal interval is enough: two ticks inside one fast test happen
    # microseconds apart in monotonic time, nowhere close to 300s -- no
    # need for an inflated value here.
    process.user_env_path("alice").write_text(
        "CONFLUENCE_POLL_ENABLED=true\nCONFLUENCE_POLL_INTERVAL_SECONDS=300\n"
    )

    polled = []

    async def _fake_poll_once(settings):
        polled.append(settings.data_dir)
        return []

    call_count = 0

    async def _fake_sleep(seconds):
        nonlocal call_count
        call_count += 1
        await real_sleep(0)  # let this tick's create_task(...), if any, run first
        if call_count >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(poller, "poll_once", _fake_poll_once)
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await poller.poll_scan_loop()

    # Polled on the first tick (never polled before -- always eligible
    # regardless of interval, see poll_scan_loop), then skipped on the
    # second -- 300s hasn't elapsed since the first poll.
    assert len(polled) == 1

    get_process_config.cache_clear()
    get_settings.cache_clear()
