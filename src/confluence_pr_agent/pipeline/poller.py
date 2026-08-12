"""Polling: the actual trigger mechanism, since Confluence Cloud has no
self-service way to register an arbitrary webhook URL (see config.py's
CONFLUENCE_POLL_* fields). Finds every page carrying CONFLUENCE_ALLOWED_LABELS
via CQL search and runs the pipeline for each -- run_pipeline's own diff/
checksum dedup (confluence/diff.py) makes re-polling an unchanged page a
cheap no-op, not a wasted pipeline run, so there's no separate "already
seen" bookkeeping needed here.

Multi-tenant: poll_scan_loop is the single scheduled task (started once from
webhook/app.py's lifespan) that polls every provisioned user on their own
schedule -- see its docstring for why a periodic filesystem scan, not N
independent per-user asyncio tasks, is the discovery mechanism.
"""

from __future__ import annotations

import asyncio
import logging
import time

from confluence_pr_agent.config import Settings, get_process_config, get_settings
from confluence_pr_agent.models import PipelineResult
from confluence_pr_agent.pipeline.orchestrator import build_deps, run_pipeline

logger = logging.getLogger(__name__)

# One lock per user (keyed by their data_dir, which is already a unique
# per-user path -- see config.py::get_settings), not a single global lock --
# guards against the scan loop and a manual "Poll now" click (or two manual
# clicks) for the SAME user overlapping, without making two different
# users' poll cycles block each other. Without this, two overlapping cycles
# for one user could both discover the same changed page and race to open
# two PRs / two Jira issues for one spec change.
_poll_locks: dict[str, asyncio.Lock] = {}


def _lock_for(settings: Settings) -> asyncio.Lock:
    # setdefault is one atomic expression -- no `await` between checking
    # for an existing lock and inserting a new one, so this can't race even
    # across concurrently-scheduled coroutines in the same event loop.
    return _poll_locks.setdefault(settings.data_dir, asyncio.Lock())


async def poll_once(settings: Settings) -> list[PipelineResult]:
    """One poll cycle for one user: discover pages, run the pipeline for
    each, return every result. Builds a single PipelineDeps and reuses it
    across all the pages found (rather than letting each run_pipeline call
    build/close its own), so a poll that finds several pages doesn't open a
    fresh set of HTTP clients per page.

    A no-op (returns []) if a cycle is already in flight for this same
    user -- see _poll_locks.
    """
    lock = _lock_for(settings)
    if lock.locked():
        logger.info("A poll cycle is already in progress for %s; skipping this trigger.", settings.data_dir)
        return []

    async with lock:
        deps = build_deps(settings)
        try:
            labels = settings.confluence_allowed_labels_list
            page_ids = await deps.confluence.search_page_ids(settings.confluence_space_key, labels)
            logger.info(
                "Poll found %d page(s) in space %s%s",
                len(page_ids),
                settings.confluence_space_key,
                f" with labels {labels}" if labels else "",
            )

            results = []
            for page_id in page_ids:
                try:
                    results.append(await run_pipeline(page_id, deps=deps))
                except Exception:
                    # One bad page (a transient API error, an unexpected
                    # payload shape) must not stop the rest of the batch --
                    # run_pipeline already fails open for problems it
                    # foresees, this is the backstop for the ones it doesn't.
                    logger.exception("Poll-triggered run failed for page %s", page_id)
            return results
        finally:
            await deps.confluence.aclose()
            await deps.github.aclose()
            await deps.email_client.aclose()
            await deps.jira.aclose()


POLL_SCAN_TICK_SECONDS = 30


async def _poll_and_log(username: str, settings: Settings) -> None:
    try:
        await poll_once(settings)
    except Exception:
        logger.exception("Poll cycle failed for user %s", username)


async def poll_scan_loop() -> None:
    """Started once from webhook/app.py's lifespan, runs until cancelled.
    Ticks every POLL_SCAN_TICK_SECONDS and scans {DATA_DIR}/users/*/ for
    provisioned users rather than managing one asyncio.Task per user --
    simpler (no task lifecycle to start/stop as users are provisioned or
    removed) and gets deprovisioning for free: delete a user's directory
    and they silently stop being polled next tick, no separate bookkeeping.

    Each eligible user's poll_once() runs as its own task (not awaited
    inline in the scan loop) so users poll fully concurrently and one
    user's slow cycle can't delay another's, or delay the next scan tick.

    last_polled is in-memory only and resets on process restart -- accepted
    tradeoff: the first tick after any redeploy polls every enabled user at
    once, which is irrelevant at the scale this runs at.
    """
    last_polled: dict[str, float] = {}
    process = get_process_config()
    while True:
        try:
            if process.users_dir_path.exists():
                for user_dir in process.users_dir_path.iterdir():
                    if not user_dir.is_dir():
                        continue
                    username = user_dir.name
                    settings = get_settings(username)
                    if not settings.confluence_poll_enabled:
                        continue
                    now = time.monotonic()
                    last_polled_at = last_polled.get(username)
                    # last_polled_at is None (not 0.0) for "never polled in
                    # this process" -- always eligible in that case,
                    # regardless of interval. time.monotonic()'s reference
                    # point isn't guaranteed to be near zero (it's often
                    # host/system uptime, which can already exceed a large
                    # configured interval on a long-lived host) or far from
                    # it (a fresh container's monotonic clock can start
                    # near zero) -- treating an unset last-polled time as
                    # "0.0 seconds ago" would make CONFLUENCE_POLL_INTERVAL_
                    # SECONDS >= current monotonic value incorrectly delay
                    # a user's very first poll after startup.
                    if last_polled_at is not None and now - last_polled_at < settings.confluence_poll_interval_seconds:
                        continue
                    last_polled[username] = now
                    asyncio.create_task(_poll_and_log(username, settings))
        except Exception:
            logger.exception("Poll scan tick failed")
        await asyncio.sleep(POLL_SCAN_TICK_SECONDS)
