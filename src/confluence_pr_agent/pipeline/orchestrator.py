"""Orchestrates the full pipeline:

Confluence page changed -> diff vs. last-seen version -> clone target repo ->
a pluggable change engine implements the change + tests -> run tests locally
(gate) -> commit/push/open PR -> email the team.

Which change engine actually writes the code (Claude Code, Cursor, GitHub
Copilot, ...) is a config choice (CHANGE_AGENT_ENGINE), not something this
module knows about -- see agent/base.py and agent/factory.py.

The page-version store is only updated on a fully successful run, so a
failed attempt (agent failure, failing tests, PR error) is retried from the
same diff on the next webhook delivery / manual re-trigger rather than being
silently marked as processed.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from confluence_pr_agent.agent.base import ChangeEngine
from confluence_pr_agent.agent.factory import build_change_engine
from confluence_pr_agent.config import Settings, get_settings
from confluence_pr_agent.confluence.client import ConfluenceClient
from confluence_pr_agent.confluence.diff import compute_diff
from confluence_pr_agent.models import PipelineResult, RunRecord
from confluence_pr_agent.notifications.sendgrid_client import SendGridClient
from confluence_pr_agent.notifications.templates import build_summary_email
from confluence_pr_agent.repo.git_client import GitClient
from confluence_pr_agent.repo.github_client import GitHubClient
from confluence_pr_agent.storage.page_store import PageStore, StoredPage
from confluence_pr_agent.storage.run_store import RunStore
from confluence_pr_agent.testing.test_runner import run_tests

logger = logging.getLogger(__name__)


@dataclass
class PipelineDeps:
    """Injected collaborators -- lets tests substitute fakes for each stage."""

    settings: Settings
    confluence: ConfluenceClient
    store: PageStore
    git: GitClient
    github: GitHubClient
    sendgrid: SendGridClient
    change_engine: ChangeEngine
    run_store: RunStore


def build_deps(settings: Settings | None = None) -> PipelineDeps:
    settings = settings or get_settings()
    return PipelineDeps(
        settings=settings,
        confluence=ConfluenceClient(
            base_url=settings.confluence_base_url,
            email=settings.confluence_user_email,
            api_token=settings.confluence_api_token,
        ),
        store=PageStore(settings.page_store_path),
        git=GitClient(settings.github_token),
        github=GitHubClient(settings.github_token),
        sendgrid=SendGridClient(settings.sendgrid_api_key),
        change_engine=build_change_engine(settings),
        run_store=RunStore(settings.runs_store_path),
    )


async def run_pipeline(page_id: str, deps: PipelineDeps | None = None) -> PipelineResult:
    owns_deps = deps is None
    deps = deps or build_deps()
    settings = deps.settings

    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    start_clock = time.monotonic()

    # Written immediately, before any actual work -- so a run in progress
    # shows up in /ui/runs as status="running" rather than being invisible
    # until it finishes (which, for a real agentic engine, can take minutes).
    # If the process dies mid-run this placeholder is left behind rather
    # than ever reaching a terminal status; the delete button in /ui/runs is
    # the way to clean one of those up.
    deps.run_store.upsert_run(
        RunRecord(
            run_id=run_id,
            started_at=started_at.isoformat(),
            finished_at=started_at.isoformat(),
            duration_seconds=0.0,
            page_id=page_id,
            page_title="",
            confluence_url="",
            engine=settings.change_agent_engine,
            target_repo=settings.target_repo,
            status="running",
        )
    )

    def finish(result: PipelineResult) -> PipelineResult:
        """Records this run (any outcome) before returning it."""
        page = result.page
        change = result.change
        pull_request = result.pull_request
        tests = result.tests
        deps.run_store.upsert_run(
            RunRecord(
                run_id=run_id,
                started_at=started_at.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                duration_seconds=time.monotonic() - start_clock,
                page_id=page_id,
                page_title=page.title if page else "",
                confluence_url=page.url if page else "",
                engine=settings.change_agent_engine,
                target_repo=settings.target_repo,
                status=result.status,
                files_changed=change.files_changed if change else [],
                pr_number=pull_request.number if pull_request else None,
                pr_url=pull_request.url if pull_request else None,
                summary=change.summary if change else None,
                error=result.error,
                email_sent=result.email_sent,
                email_error=result.email_error,
                usage=change.usage if change else None,
                raw_log=(change.raw_log[-8000:] if change and change.raw_log else None),
                test_output=(tests.output[-8000:] if tests and tests.output else None),
            )
        )
        return result

    try:
        page = await deps.confluence.fetch_page(page_id)
        diff = compute_diff(deps.store, page)

        if not diff.is_first_seen and diff.diff_text == "":
            if diff.content_unchanged:
                logger.info(
                    "Page %s version bumped (v%s -> v%s) but content checksum matched; skipping.",
                    page_id,
                    diff.previous_version,
                    page.version,
                )
            else:
                logger.info("No version change for page %s (still v%s); skipping.", page_id, page.version)
            return finish(PipelineResult(status="no_change_detected", page=page, diff=diff))

        logger.info(
            "Detected change on page %s: v%s -> v%s", page_id, diff.previous_version, page.version
        )

        repo_dir = settings.workdirs_path / f"page-{page_id}-v{page.version}"
        branch_name = f"confluence-sync/page-{page_id}-v{page.version}-{int(time.time())}"

        await deps.git.clone(settings.target_repo, repo_dir, settings.target_repo_base_branch)
        await deps.git.create_branch(repo_dir, branch_name)

        change = await deps.change_engine.implement_change(repo_dir, diff, settings.change_agent_max_turns)

        if not change.success:
            logger.error("Change engine did not complete successfully for page %s", page_id)
            return finish(
                PipelineResult(status="error", page=page, diff=diff, change=change, error="change agent failed")
            )

        if not await deps.git.has_changes(repo_dir):
            logger.warning("Change agent made no file changes for page %s", page_id)
            return finish(
                PipelineResult(
                    status="error", page=page, diff=diff, change=change, error="agent made no file changes"
                )
            )

        change.files_changed = await deps.git.changed_files(repo_dir)

        tests = await run_tests(repo_dir, settings.target_repo_test_command)
        if not tests.passed:
            logger.error("Tests failed for page %s change; not opening a PR.", page_id)
            return finish(
                PipelineResult(status="tests_failed", page=page, diff=diff, change=change, tests=tests)
            )

        commit_message = f"Sync with Confluence spec: {page.title} (v{page.version})\n\n{change.summary}"
        await deps.git.commit_all(repo_dir, commit_message)
        await deps.git.push(repo_dir, branch_name)

        pr_body = (
            f"**Source:** [{page.title}]({page.url}) (v{diff.previous_version} -> v{page.version})\n\n"
            f"**Summary of change:**\n{change.summary}\n\n"
            "**Files changed:**\n" + "\n".join(f"- `{f}`" for f in change.files_changed) + "\n\n"
            "_Opened automatically by confluence-pr-agent._"
        )
        pull_request = await deps.github.open_pull_request(
            owner_repo=settings.target_repo,
            head_branch=branch_name,
            base_branch=settings.target_repo_base_branch,
            title=f"Sync with Confluence: {page.title} (v{page.version})",
            body=pr_body,
        )

        deps.store.put(
            StoredPage(
                page_id=page.page_id,
                title=page.title,
                version=page.version,
                body_html=page.body_html,
                body_checksum=diff.body_checksum,
                url=page.url,
            )
        )

        # Best-effort and deliberately isolated: the PR is already open at
        # this point, so a broken/unconfigured email step must not turn a
        # successful run into a reported failure (it did, before this was
        # fixed -- a blank SENDGRID_API_KEY produced an unhandled
        # httpx.LocalProtocolError here that the outer `except` caught,
        # discarding the pull_request from the recorded result entirely).
        email_sent = False
        email_error: str | None = None
        if not settings.sendgrid_api_key:
            email_error = "SENDGRID_API_KEY not configured; skipped"
            logger.info("Skipping summary email for PR #%s: %s", pull_request.number, email_error)
        else:
            try:
                subject, text_body, html_body = build_summary_email(diff, change, pull_request)
                await deps.sendgrid.send_email(
                    from_address=settings.email_from_address,
                    to_addresses=settings.email_to_list,
                    subject=subject,
                    text_body=text_body,
                    html_body=html_body,
                )
                email_sent = True
            except Exception as exc:
                email_error = str(exc)
                logger.warning("PR #%s opened but the summary email failed to send: %s", pull_request.number, exc)

        logger.info("Opened PR #%s for page %s: %s", pull_request.number, page_id, pull_request.url)
        return finish(
            PipelineResult(
                status="opened_pr",
                page=page,
                diff=diff,
                change=change,
                tests=tests,
                pull_request=pull_request,
                email_sent=email_sent,
                email_error=email_error,
            )
        )

    except Exception as exc:
        logger.exception("Pipeline failed for page %s", page_id)
        return finish(PipelineResult(status="error", error=str(exc)))
    finally:
        if owns_deps:
            await deps.confluence.aclose()
            await deps.github.aclose()
            await deps.sendgrid.aclose()
