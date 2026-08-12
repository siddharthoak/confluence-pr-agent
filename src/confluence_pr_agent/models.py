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
    labels: list[str] = field(default_factory=list)


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
class JudgeCriterion:
    """One independently-scored dimension of the judge's review -- see
    judge/prompts.py::CRITERIA for the fixed set of three. Rendered as a
    row in the rubric table attached to the PR body.
    """

    key: str  # e.g. "implements_spec" -- matches judge/prompts.py::CRITERIA
    label: str  # human-readable, e.g. "Implements the spec change"
    assessment: str  # "pass" | "warning" | "fail"
    note: str  # one sentence, specific to this diff


@dataclass
class JudgeResult:
    """Verdict from the LLM-as-judge review (pipeline/orchestrator.py),
    which runs after tests pass but before a PR is opened -- a green test
    suite doesn't prove the spec was actually implemented (or implemented
    without unrelated changes), so this is a second, semantic review.

    `verdict` is derived from `criteria` (judge/prompts.py::derive_verdict),
    not reported by the model directly -- any "fail" criterion makes the
    whole thing "rejected", any "warning" with no "fail" makes it
    "approved_with_warnings", otherwise "approved". Unlike the tests gate,
    the judge never blocks a PR from opening -- see orchestrator.py for how
    "rejected" changes what kind of PR opens instead of stopping the run.
    """

    verdict: str  # "approved" | "approved_with_warnings" | "rejected" | "skipped" (disabled, or the call failed)
    reasoning: str
    concerns: list[str] = field(default_factory=list)
    criteria: list[JudgeCriterion] = field(default_factory=list)


@dataclass
class PullRequestResult:
    number: int
    url: str
    branch: str
    draft: bool = False


@dataclass
class PullRequestStatus:
    """Current state of a previously-opened PR, fetched fresh each run to
    decide whether to reuse its branch -- see pipeline/orchestrator.py.
    """

    number: int
    state: str  # "open" | "closed"
    merged: bool

    @property
    def is_open(self) -> bool:
        return self.state == "open"


@dataclass
class JiraIssueResult:
    key: str  # e.g. "SD-123"
    url: str


@dataclass
class JiraIssueStatus:
    """Current state of a previously-created Jira issue, fetched fresh each
    run to decide whether to reuse it -- mirrors PullRequestStatus's role
    for PR-branch reuse. Jira's statusCategory (not the workflow-specific
    status name, which varies per project) is the reliable "is this done"
    signal across arbitrary team workflows.
    """

    key: str
    status_name: str
    status_category: str  # "new" | "indeterminate" | "done"

    @property
    def is_open(self) -> bool:
        return self.status_category != "done"


@dataclass
class PipelineResult:
    # "opened_pr" | "no_change_detected" | "tests_failed" | "judge_rejected" | "error" | "ignored"
    # judge_rejected still carries a `pull_request` -- the judge never blocks
    # PR creation, it only changes the PR into a flagged draft. Only a
    # tests_failed/error/ignored/no_change_detected run has no PR.
    status: str
    page: PageSnapshot | None = None
    diff: PageDiff | None = None
    change: ChangeAgentResult | None = None
    tests: RepoTestResult | None = None
    judge: JudgeResult | None = None
    pull_request: PullRequestResult | None = None
    # True when `pull_request` is an existing still-open PR that was updated
    # in place (new commits pushed, title/body/labels refreshed) rather than
    # a brand-new one -- see pipeline/orchestrator.py's branch-reuse logic.
    reused_pr: bool = False
    jira_issue: JiraIssueResult | None = None
    jira_reused: bool = False  # true if an existing still-open story was commented on rather than a new one created
    error: str | None = None
    # Email is best-effort and independent of pipeline success: a PR that
    # opened successfully stays status="opened_pr" even if the notification
    # email fails afterward (e.g. SendGrid not configured) -- that failure
    # is recorded here instead of overwriting the whole run as an error.
    email_sent: bool = False
    email_error: str | None = None
    attempts: int = 1  # how many ai_agent/run_tests cycles this run took -- see change_agent_max_attempts


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
    current_stage: str | None = None  # last stage entered -- see pipeline/stages.py
    files_changed: list[str] = field(default_factory=list)
    pr_number: int | None = None
    pr_url: str | None = None
    pr_draft: bool = False  # true when the judge rejected but a flagged PR still opened -- see orchestrator.py
    reused_pr: bool = False  # true if this run updated an existing still-open PR instead of opening a new one
    summary: str | None = None
    error: str | None = None
    email_sent: bool = False
    email_error: str | None = None
    usage: dict | None = None
    raw_log: str | None = None  # tail of the engine's own output; detail-page only
    test_output: str | None = None  # tail of the target repo's test command output; detail-page only
    judge_verdict: str | None = None  # "approved" | "approved_with_warnings" | "rejected" | "skipped"
    judge_reasoning: str | None = None
    judge_concerns: list[str] = field(default_factory=list)
    judge_criteria: list[JudgeCriterion] = field(default_factory=list)
    spec_diff: str | None = None  # the Confluence diff text the agent was actually prompted with
    attempts: int = 1  # how many ai_agent/run_tests cycles this run took -- see agent_max_attempts
    jira_issue_key: str | None = None
    jira_issue_url: str | None = None
    jira_reused: bool = False  # true if an existing still-open story was commented on rather than a new one created
