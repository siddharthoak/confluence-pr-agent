"""Shared data types passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageSnapshot:
    """A single fetched revision of a Confluence page."""

    page_id: str
    title: str
    version: int
    body_html: str
    url: str


@dataclass
class PageDiff:
    """What changed between the previously stored snapshot and the current one."""

    page: PageSnapshot
    previous_version: int | None
    diff_text: str
    is_first_seen: bool
    body_checksum: str  # sha256 of page's normalized plain-text body -- see confluence/diff.py
    content_unchanged: bool = False  # version bumped (e.g. metadata edit) but checksum matched


@dataclass
class ChangeAgentResult:
    """Output of the code-change agent run against the target repo."""

    success: bool
    summary: str
    files_changed: list[str] = field(default_factory=list)
    raw_log: str = ""
    # Whatever token/cost usage the engine's own output reported, passed
    # through as-is rather than normalized -- each CLI reports this
    # differently (or not at all) and the shapes aren't worth force-fitting
    # into one schema. None means the engine didn't report anything parseable.
    usage: dict | None = None


@dataclass
class RepoTestResult:
    passed: bool
    output: str
    command: str


@dataclass
class PullRequestResult:
    number: int
    url: str
    branch: str


@dataclass
class PipelineResult:
    status: str  # "opened_pr" | "no_change_detected" | "tests_failed" | "error"
    page: PageSnapshot | None = None
    diff: PageDiff | None = None
    change: ChangeAgentResult | None = None
    tests: RepoTestResult | None = None
    pull_request: PullRequestResult | None = None
    error: str | None = None
    # Email is best-effort and independent of pipeline success: a PR that
    # opened successfully stays status="opened_pr" even if the notification
    # email fails afterward (e.g. SendGrid not configured) -- that failure
    # is recorded here instead of overwriting the whole run as an error.
    email_sent: bool = False
    email_error: str | None = None


@dataclass
class RunRecord:
    """One row in the run-history store (data/runs.json) -- what the /ui/runs
    dashboard lists, and /ui/runs/{run_id} shows in full. Written once per
    pipeline invocation, regardless of outcome, so failed/skipped runs stay
    visible too.
    """

    run_id: str
    started_at: str  # ISO 8601
    finished_at: str  # ISO 8601
    duration_seconds: float
    page_id: str
    page_title: str
    confluence_url: str
    engine: str
    target_repo: str
    status: str
    files_changed: list[str] = field(default_factory=list)
    pr_number: int | None = None
    pr_url: str | None = None
    summary: str | None = None
    error: str | None = None
    email_sent: bool = False
    email_error: str | None = None
    usage: dict | None = None
    raw_log: str | None = None  # tail of the engine's own output; detail-page only
    test_output: str | None = None  # tail of the target repo's test command output; detail-page only
