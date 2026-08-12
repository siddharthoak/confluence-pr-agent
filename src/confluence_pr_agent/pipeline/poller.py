"""Polling: the actual trigger mechanism, since Confluence Cloud has no
self-service way to register an arbitrary webhook URL (see config.py's
CONFLUENCE_POLL_* fields). Finds every page carrying CONFLUENCE_ALLOWED_LABELS
via CQL search and runs the pipeline for each -- run_pipeline's own diff/
checksum dedup (confluence/diff.py) makes re-polling an unchanged page a
cheap no-op, not a wasted pipeline run, so there's no separate "already
seen" bookkeeping needed here.
"""

from __future__ import annotations

import asyncio
import logging

from confluence_pr_agent.config import Settings, get_settings
from confluence_pr_agent.models import PipelineResult
from confluence_pr_agent.pipeline.orchestrator import build_deps, run_pipeline

logger = logging.getLogger(__name__)

# Guards against the scheduled loop and a manual "Poll now" click (or two
# manual clicks) overlapping -- without this, both could discover the same
# changed page and race to open two PRs / two Jira issues for one spec
# change. poll_loop and ui/routes.py::trigger_poll are the only callers;
# either going through poll_once means neither has to reason about the
# other's timing.
_poll_lock = asyncio.Lock()


async def poll_once(settings: Settings | None = None) -> list[PipelineResult]:
    """One poll cycle: discover pages, run the pipeline for each, return
    every result. Builds a single PipelineDeps and reuses it across all the
    pages found (rather than letting each run_pipeline call build/close its
    own), so a poll that finds several pages doesn't open a fresh set of
    HTTP clients per page.

    A no-op (returns []) if a cycle is already in flight -- see _poll_lock.
    """
    if _poll_lock.locked():
        logger.info("A poll cycle is already in progress; skipping this trigger.")
        return []

    async with _poll_lock:
        settings = settings or get_settings()
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


async def poll_loop(settings: Settings | None = None) -> None:
    """Runs poll_once on a timer until cancelled. Started from the app's
    lifespan (webhook/app.py) when CONFLUENCE_POLL_ENABLED is set; a plain
    asyncio background task rather than a separate scheduler process, per
    this project's "no extra infra" style.
    """
    settings = settings or get_settings()
    while True:
        try:
            await poll_once(settings)
        except Exception:
            logger.exception("Poll cycle failed")
        await asyncio.sleep(max(1, settings.confluence_poll_interval_seconds))
