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


async def test_poll_loop_calls_poll_once_on_an_interval_until_cancelled(settings, monkeypatch):
    settings.confluence_poll_interval_seconds = 5
    calls = []

    async def _fake_poll_once(s):
        calls.append(s)
        return []

    async def _fake_sleep(seconds):
        assert seconds == 5
        raise asyncio.CancelledError()

    monkeypatch.setattr(poller, "poll_once", _fake_poll_once)
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await poller.poll_loop(settings)

    assert len(calls) == 1
