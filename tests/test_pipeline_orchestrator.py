from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from confluence_pr_agent.confluence.diff import _to_plain_text, compute_checksum
from confluence_pr_agent.models import ChangeAgentResult, PageSnapshot, PullRequestResult, RepoTestResult
from confluence_pr_agent.pipeline import orchestrator
from confluence_pr_agent.pipeline.orchestrator import PipelineDeps, run_pipeline
from confluence_pr_agent.storage.page_store import PageStore, StoredPage
from confluence_pr_agent.storage.run_store import RunStore


def _page(version: int, body: str = "<p>spec</p>", labels: list[str] | None = None) -> PageSnapshot:
    return PageSnapshot(
        page_id="123456",
        title="Checkout Flow Spec",
        version=version,
        body_html=body,
        url="https://example.atlassian.net/wiki/spaces/SD/pages/123456",
        labels=labels or [],
    )


def _stored(version: int, body_html: str, url: str) -> StoredPage:
    return StoredPage(
        page_id="123456",
        title="Checkout Flow Spec",
        version=version,
        body_html=body_html,
        body_checksum=compute_checksum(_to_plain_text(body_html)),
        url=url,
    )


def _make_deps(settings, *, page: PageSnapshot) -> PipelineDeps:
    confluence = AsyncMock()
    confluence.fetch_page.return_value = page

    git = AsyncMock()
    git.has_changes.return_value = True
    git.changed_files.return_value = ["src/checkout.py", "tests/test_checkout.py"]

    github = AsyncMock()
    github.open_pull_request.return_value = PullRequestResult(
        number=7, url="https://github.com/acme/widgets/pull/7", branch="confluence-sync/x"
    )

    sendgrid = AsyncMock()
    store = PageStore(settings.page_store_path)

    change_engine = AsyncMock()
    change_engine.implement_change.return_value = ChangeAgentResult(
        success=True, summary="Added PayPal support."
    )

    return PipelineDeps(
        settings=settings,
        confluence=confluence,
        store=store,
        git=git,
        github=github,
        sendgrid=sendgrid,
        change_engine=change_engine,
        run_store=RunStore(settings.runs_store_path),
    )


async def test_no_change_detected_skips_everything(settings):
    page = _page(1)
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, page.body_html, page.url))

    result = await run_pipeline("123456", deps=deps)

    assert result.status == "no_change_detected"
    deps.git.clone.assert_not_called()
    deps.change_engine.implement_change.assert_not_called()
    deps.github.open_pull_request.assert_not_called()
    deps.sendgrid.send_email.assert_not_called()


async def test_page_without_required_label_is_ignored_before_any_real_work(settings):
    settings.confluence_allowed_labels = "brd,spec-for-agent"
    page = _page(1, labels=["meeting-notes"])
    deps = _make_deps(settings, page=page)

    result = await run_pipeline("123456", deps=deps)

    assert result.status == "ignored"
    assert "brd" in (result.error or "")
    deps.git.clone.assert_not_called()
    deps.change_engine.implement_change.assert_not_called()
    deps.github.open_pull_request.assert_not_called()
    deps.sendgrid.send_email.assert_not_called()

    runs = deps.run_store.list_runs()
    assert runs[0]["status"] == "ignored"


async def test_page_label_match_is_case_insensitive(settings, monkeypatch):
    settings.confluence_allowed_labels = "BRD"
    page = _page(2, body="<p>spec v2</p>", labels=["brd"])
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, "<p>spec v1</p>", page.url))

    async def _fake_run_tests(repo_dir, command):
        return RepoTestResult(passed=True, output="2 passed", command=command)

    monkeypatch.setattr(orchestrator, "run_tests", _fake_run_tests)

    result = await run_pipeline("123456", deps=deps)

    assert result.status == "opened_pr"


async def test_no_allowed_labels_configured_means_no_filtering(settings):
    """Empty CONFLUENCE_ALLOWED_LABELS (the default) processes every page --
    this is the backward-compatible behavior for anyone who hasn't set up
    labels at all.
    """
    settings.confluence_allowed_labels = ""
    page = _page(1, labels=[])  # no labels on the page at all
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, page.body_html, page.url))

    result = await run_pipeline("123456", deps=deps)

    # falls through to the normal no-op path (same version, no labels involved)
    assert result.status == "no_change_detected"


async def test_successful_change_opens_pr_and_emails_team(settings, monkeypatch):
    page = _page(2, body="<p>spec v2</p>")
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, "<p>spec v1</p>", page.url))

    async def _fake_run_tests(repo_dir, command):
        return RepoTestResult(passed=True, output="2 passed", command=command)

    monkeypatch.setattr(orchestrator, "run_tests", _fake_run_tests)

    result = await run_pipeline("123456", deps=deps)

    assert result.status == "opened_pr"
    assert result.pull_request is not None
    assert result.pull_request.number == 7
    deps.change_engine.implement_change.assert_awaited_once()
    deps.git.clone.assert_awaited_once()
    deps.git.push.assert_awaited_once()
    deps.github.open_pull_request.assert_awaited_once()
    deps.sendgrid.send_email.assert_awaited_once()

    stored = deps.store.get("123456")
    assert stored is not None
    assert stored["version"] == 2

    runs = deps.run_store.list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "opened_pr"
    assert runs[0]["engine"] == settings.change_agent_engine
    assert runs[0]["pr_number"] == 7
    assert runs[0]["pr_url"] == "https://github.com/acme/widgets/pull/7"
    assert runs[0]["files_changed"] == ["src/checkout.py", "tests/test_checkout.py"]
    assert runs[0]["duration_seconds"] >= 0
    assert runs[0]["current_stage"] == "send_email"
    assert runs[0]["spec_diff"] is not None
    assert "spec v2" in runs[0]["spec_diff"]


async def test_a_running_placeholder_is_visible_before_the_pipeline_finishes(settings, monkeypatch):
    page = _page(2, body="<p>spec v2</p>")
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, "<p>spec v1</p>", page.url))

    observed_mid_run = {}

    async def _clone_side_effect(*args, **kwargs):
        runs = deps.run_store.list_runs()
        if runs:
            observed_mid_run["status"] = runs[0]["status"]
            observed_mid_run["current_stage"] = runs[0]["current_stage"]

    deps.git.clone.side_effect = _clone_side_effect

    async def _fake_run_tests(repo_dir, command):
        return RepoTestResult(passed=True, output="2 passed", command=command)

    monkeypatch.setattr(orchestrator, "run_tests", _fake_run_tests)

    result = await run_pipeline("123456", deps=deps)

    assert observed_mid_run["status"] == "running"
    assert observed_mid_run["current_stage"] == "clone_repo"
    # ... and the placeholder is replaced, not left behind as a second row
    assert result.status == "opened_pr"
    runs = deps.run_store.list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "opened_pr"


async def test_failing_tests_blocks_pr_and_does_not_advance_store(settings, monkeypatch):
    page = _page(2, body="<p>spec v2</p>")
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, "<p>spec v1</p>", page.url))

    async def _fake_run_tests(repo_dir, command):
        return RepoTestResult(passed=False, output="1 failed: ModuleNotFoundError: no module named 'django'", command=command)

    monkeypatch.setattr(orchestrator, "run_tests", _fake_run_tests)

    result = await run_pipeline("123456", deps=deps)

    assert result.status == "tests_failed"
    deps.github.open_pull_request.assert_not_called()
    deps.sendgrid.send_email.assert_not_called()

    stored = deps.store.get("123456")
    assert stored is not None
    assert stored["version"] == 1

    runs = deps.run_store.list_runs()
    assert "ModuleNotFoundError" in runs[0]["test_output"]
    assert runs[0]["current_stage"] == "run_tests"


async def test_change_engine_failure_does_not_open_pr(settings):
    page = _page(2, body="<p>spec v2</p>")
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, "<p>spec v1</p>", page.url))
    deps.change_engine.implement_change.return_value = ChangeAgentResult(
        success=False, summary="Ran out of turns."
    )

    result = await run_pipeline("123456", deps=deps)

    assert result.status == "error"
    deps.github.open_pull_request.assert_not_called()
    deps.sendgrid.send_email.assert_not_called()

    runs = deps.run_store.list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert runs[0]["current_stage"] == "ai_agent"


async def test_no_change_detected_is_still_recorded_as_a_run(settings):
    page = _page(1)
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, page.body_html, page.url))

    await run_pipeline("123456", deps=deps)

    runs = deps.run_store.list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "no_change_detected"
    assert runs[0]["spec_diff"] is None  # nothing to show -- diff_text is empty for an unchanged page


async def test_missing_sendgrid_key_skips_email_without_failing_the_run(settings, monkeypatch):
    settings.sendgrid_api_key = ""
    page = _page(2, body="<p>spec v2</p>")
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, "<p>spec v1</p>", page.url))

    async def _fake_run_tests(repo_dir, command):
        return RepoTestResult(passed=True, output="2 passed", command=command)

    monkeypatch.setattr(orchestrator, "run_tests", _fake_run_tests)

    result = await run_pipeline("123456", deps=deps)

    assert result.status == "opened_pr"
    assert result.pull_request is not None
    assert result.email_sent is False
    assert "not configured" in (result.email_error or "")
    deps.sendgrid.send_email.assert_not_called()

    runs = deps.run_store.list_runs()
    assert runs[0]["status"] == "opened_pr"
    assert runs[0]["pr_number"] == 7
    assert runs[0]["email_sent"] is False


async def test_email_send_failure_does_not_erase_the_successful_pr(settings, monkeypatch):
    """Regression test: a blank/invalid SendGrid key used to raise an
    unhandled exception from send_email *after* the PR was already opened,
    which the outer except-block caught and reported as a total failure --
    discarding the pull_request from the recorded result even though a real
    PR existed on GitHub. Confirmed live against care-scheduler PR #1.
    """
    page = _page(2, body="<p>spec v2</p>")
    deps = _make_deps(settings, page=page)
    deps.store.put(_stored(1, "<p>spec v1</p>", page.url))
    deps.sendgrid.send_email.side_effect = RuntimeError("Illegal header value b'Bearer '")

    async def _fake_run_tests(repo_dir, command):
        return RepoTestResult(passed=True, output="2 passed", command=command)

    monkeypatch.setattr(orchestrator, "run_tests", _fake_run_tests)

    result = await run_pipeline("123456", deps=deps)

    assert result.status == "opened_pr"
    assert result.pull_request is not None
    assert result.pull_request.url == "https://github.com/acme/widgets/pull/7"
    assert result.email_sent is False
    assert "Bearer" in (result.email_error or "")

    runs = deps.run_store.list_runs()
    assert runs[0]["status"] == "opened_pr"
    assert runs[0]["pr_url"] == "https://github.com/acme/widgets/pull/7"
    assert runs[0]["email_error"] is not None

    # And the page store still advances -- the actual code change/PR did
    # succeed, so this should not be retried on the next webhook delivery.
    stored = deps.store.get("123456")
    assert stored is not None
    assert stored["version"] == 2
