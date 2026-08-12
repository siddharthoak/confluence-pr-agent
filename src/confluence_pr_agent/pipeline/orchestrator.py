"""Orchestrates the full pipeline:

Confluence page changed -> diff vs. last-seen version -> clone target repo ->
a pluggable change engine implements the change + tests -> run tests locally
(gate, with a bounded self-correction retry loop) -> an LLM judge reviews
the diff (never blocks -- only changes what kind of PR opens) -> commit/push
/open PR -> email the team.

Which change engine actually writes the code (Claude Code, Cursor, GitHub
Copilot, ...) is a config choice (CHANGE_AGENT_ENGINE), not something this
module knows about -- see agent/base.py and agent/factory.py. Same for which
model reviews it (JUDGE_PROVIDER) -- see judge/base.py and judge/factory.py.

The only two things that stop a PR from opening at all are: the change
engine failing outright / making no changes, and the test suite still
failing after every retry attempt. The LLM judge is advisory, not a gate --
a "rejected" verdict still opens a PR, just as a draft flagged "[Needs
Work]" with its rubric attached, instead of silently doing nothing. This is
deliberate: the pipeline runs unattended (webhook-triggered), so there is no
one present to act on a pipeline-internal "are you sure?" -- the one place a
human reviews this system's output is at PR merge time, which this design
preserves and feeds with more information instead.

The page-version store is only updated once a PR has actually opened
(including a judge-rejected draft), so a run that produced no durable
artifact at all (agent failure, tests still failing after retries, PR API
error) is retried from the same diff on the next webhook delivery / manual
re-trigger rather than being silently marked as processed.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from confluence_pr_agent.agent.base import ChangeEngine
from confluence_pr_agent.agent.factory import build_change_engine
from confluence_pr_agent.config import Settings, get_process_config, get_settings
from confluence_pr_agent.confluence.client import ConfluenceClient
from confluence_pr_agent.confluence.diff import compute_diff
from confluence_pr_agent.jira.client import JiraClient
from confluence_pr_agent.jira.story_writer import generate_story_content
from confluence_pr_agent.judge.base import ChangeJudge
from confluence_pr_agent.judge.factory import build_judge, judge_configured
from confluence_pr_agent.models import (
    ChangeAgentResult,
    JiraIssueResult,
    JudgeResult,
    PageDiff,
    PageSnapshot,
    PipelineResult,
    RunRecord,
)
from confluence_pr_agent.notifications.base import EmailClient
from confluence_pr_agent.notifications.postmark_client import PostmarkClient
from confluence_pr_agent.notifications.sendgrid_client import SendGridClient
from confluence_pr_agent.notifications.templates import build_summary_email
from confluence_pr_agent.pipeline.stages import STAGE_KEYS
from confluence_pr_agent.repo.git_client import GitClient
from confluence_pr_agent.repo.github_client import GitHubClient
from confluence_pr_agent.storage.page_store import PageStore, StoredPage
from confluence_pr_agent.storage.run_store import RunStore
from confluence_pr_agent.testing.test_runner import run_tests

logger = logging.getLogger(__name__)

_ASSESSMENT_ICON = {"pass": "✅", "warning": "⚠️", "fail": "❌"}

# Applied to the PR based on the judge's verdict so a rejected/warned run is
# queryable via the GitHub API/CLI, not just by title-string matching. Only
# ever two labels exist between them -- a clean "approved" run means neither
# is present.
LABEL_NEEDS_WORK = "agent:needs-work"
LABEL_WARNING = "agent:warning"
_LABEL_COLOR = {LABEL_NEEDS_WORK: "d73a4a", LABEL_WARNING: "fbca04"}
_LABEL_DESCRIPTION = {
    LABEL_NEEDS_WORK: "Opened by confluence-pr-agent -- the LLM judge found at least one criterion clearly unmet.",
    LABEL_WARNING: "Opened by confluence-pr-agent -- the LLM judge approved with at least one non-blocking concern.",
}


async def _sync_verdict_label(github: GitHubClient, owner_repo: str, pr_number: int, verdict: str) -> None:
    """Best-effort and isolated, like the email step: labeling is an
    annotation on top of an already-successful PR, not something that
    should fail the run (e.g. a fine-grained PAT without the "issues" scope
    would 403 on this and must not turn an opened PR into a reported
    failure). Always resyncs both labels, not just the target one, so
    reusing an existing PR (see run_pipeline) correctly clears a stale
    label from a previous run's different verdict.
    """
    target = LABEL_NEEDS_WORK if verdict == "rejected" else LABEL_WARNING if verdict == "approved_with_warnings" else None
    try:
        if target:
            await github.ensure_label(owner_repo, target, _LABEL_COLOR[target], _LABEL_DESCRIPTION[target])
            await github.add_labels(owner_repo, pr_number, [target])
        for other in (LABEL_NEEDS_WORK, LABEL_WARNING):
            if other != target:
                await github.remove_label(owner_repo, pr_number, other)
    except Exception as exc:
        logger.warning("Failed to sync judge labels on PR #%s: %s", pr_number, exc)


def _build_pr_body(
    page: PageSnapshot, diff: PageDiff, change: ChangeAgentResult, judge_result: JudgeResult | None
) -> str:
    """PR description: source/summary/files as before, plus a rubric table
    of the judge's per-criterion review when one ran -- this is the one
    place a human actually looks, so the review needs to live here, not
    just on the internal /ui/runs/{id} page.
    """
    parts = [
        f"**Source:** [{page.title}]({page.url}) (v{diff.previous_version} -> v{page.version})\n",
        f"**Summary of change:**\n{change.summary}\n",
    ]

    if judge_result and judge_result.verdict == "rejected":
        parts.append(
            "> ⚠️ **Needs review before merge.** The LLM judge below found at least one "
            "criterion clearly unmet. This PR still opened automatically (as a draft) so nothing is "
            "lost -- fix in place on this branch, or close it, at your discretion.\n"
        )

    if judge_result and judge_result.criteria:
        rows = "\n".join(
            f"| {c.label} | {_ASSESSMENT_ICON.get(c.assessment, c.assessment)} {c.assessment} | {c.note} |"
            for c in judge_result.criteria
        )
        parts.append(
            "**LLM Judge review:**\n\n"
            "| Criterion | Assessment | Note |\n"
            "|---|---|---|\n"
            f"{rows}\n\n"
            f"{judge_result.reasoning}\n"
        )
        if judge_result.concerns:
            concerns = "\n".join(f"- {c}" for c in judge_result.concerns)
            parts.append(f"**Concerns:**\n{concerns}\n")
    elif judge_result and judge_result.verdict == "skipped":
        parts.append(f"_LLM Judge review: skipped ({judge_result.reasoning})_\n")

    parts.append("**Files changed:**\n" + "\n".join(f"- `{f}`" for f in change.files_changed) + "\n")
    parts.append("_Opened automatically by confluence-pr-agent._")
    return "\n".join(parts)


@dataclass
class PipelineDeps:
    """Injected collaborators -- lets tests substitute fakes for each stage."""

    settings: Settings
    confluence: ConfluenceClient
    store: PageStore
    git: GitClient
    github: GitHubClient
    email_client: EmailClient
    change_engine: ChangeEngine
    run_store: RunStore
    judge: ChangeJudge
    jira: JiraClient


def _build_email_client(settings: Settings) -> EmailClient:
    provider = settings.email_provider.strip().lower()
    if provider == "postmark":
        return PostmarkClient(settings.postmark_api_key)
    return SendGridClient(settings.sendgrid_api_key)  # default -- also covers an unrecognized value


def build_deps(settings: Settings | None = None) -> PipelineDeps:
    # No settings given -- resolves to the single bootstrap/default user
    # (config.py's ProcessConfig.resolved_default_user), not a bare global
    # get_settings() (multi-tenant: there's no such thing anymore, every
    # user has their own). This is what /webhook/confluence relies on (see
    # webhook/app.py) -- it has no way to know which of several users a
    # webhook delivery is "for", so it always resolves this one fixed
    # identity, same as it always has.
    settings = settings or get_settings(get_process_config().resolved_default_user)
    if settings.repo_provider != "github":
        # Fail loudly here rather than silently building a GitClient/
        # GitHubClient anyway -- REPO_PROVIDER is config surface for future
        # providers (see config.py), not something this pipeline can
        # actually act on yet. Better than quietly doing GitHub work against
        # a setting that says otherwise.
        raise ValueError(
            f"REPO_PROVIDER={settings.repo_provider!r} is not supported yet -- only 'github' is implemented."
        )
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
        email_client=_build_email_client(settings),
        change_engine=build_change_engine(settings),
        run_store=RunStore(settings.runs_store_path),
        judge=build_judge(settings),
        jira=JiraClient(
            base_url=settings.jira_base_url,
            email=settings.jira_user_email,
            api_token=settings.jira_api_token,
        ),
    )


async def run_pipeline(page_id: str, deps: PipelineDeps | None = None) -> PipelineResult:
    owns_deps = deps is None
    deps = deps or build_deps()
    settings = deps.settings

    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    start_clock = time.monotonic()

    # Declared here (not first assigned deep inside the try block) so
    # they're always safely referenceable in finish() and the outermost
    # except handler, even for a run that fails before Jira tracking would
    # otherwise be reached.
    jira_issue: JiraIssueResult | None = None
    jira_reused = False

    # Mutated as the pipeline progresses so finish() (and mark_stage itself)
    # can always report the latest known page/stage, even on a path that
    # fails before `page` would otherwise be assigned.
    progress: dict = {"stage": STAGE_KEYS[0], "page": None}

    def mark_stage(stage: str) -> None:
        """Records the stage the pipeline is currently entering, so a run in
        progress shows up in /ui/runs as status="running" with a live stage
        (not just invisible until it finishes -- which, for a real agentic
        engine, can take minutes) and so a finished run's detail page can
        show exactly how far it got. If the process dies mid-run this is
        left behind rather than ever reaching a terminal status; the delete
        button in /ui/runs is the way to clean one of those up.
        """
        assert stage in STAGE_KEYS, f"unknown stage {stage!r}"
        progress["stage"] = stage
        page = progress["page"]
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
                status="running",
                current_stage=stage,
            )
        )

    mark_stage(STAGE_KEYS[0])  # "fetch_page"

    async def _sync_jira_on_finish(result: PipelineResult) -> None:
        """Best-effort and isolated, same as everything else that touches an
        external API here: a Jira outage must never turn an otherwise
        successful (or already-failed) run into something worse. Comments
        on the tracked issue with either why the run failed (so a developer
        can pick it up manually, per the "create the story regardless"
        design) or the PR that resulted.
        """
        if not result.jira_issue:
            return
        try:
            if result.status in ("opened_pr", "judge_rejected") and result.pull_request:
                if result.status == "judge_rejected":
                    message = (
                        f"Pull request opened as a draft, flagged for review: {result.pull_request.url}\n\n"
                        "The LLM judge found at least one criterion clearly unmet -- see the PR "
                        "description for specifics."
                    )
                elif result.judge and result.judge.verdict == "approved_with_warnings":
                    message = (
                        f"Pull request opened: {result.pull_request.url}\n\n"
                        "(The LLM judge flagged non-blocking concerns -- worth a look before merging.)"
                    )
                else:
                    message = f"Pull request opened: {result.pull_request.url}"
                await deps.jira.add_comment(result.jira_issue.key, message)
            elif result.status in ("tests_failed", "error"):
                reason = result.error or (
                    result.tests.output[-2000:] if result.tests and result.tests.output else "See the run details."
                )
                await deps.jira.add_comment(
                    result.jira_issue.key,
                    f"This change could not be completed automatically:\n\n{reason}\n\n"
                    "A developer may need to pick this up manually.",
                )
        except Exception as exc:
            logger.warning("Failed to sync Jira story %s: %s", result.jira_issue.key, exc)

    async def finish(result: PipelineResult) -> PipelineResult:
        """Records this run's terminal outcome before returning it."""
        page = result.page
        diff = result.diff
        change = result.change
        pull_request = result.pull_request
        tests = result.tests
        judge = result.judge
        await _sync_jira_on_finish(result)
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
                current_stage=progress["stage"],
                files_changed=change.files_changed if change else [],
                pr_number=pull_request.number if pull_request else None,
                pr_url=pull_request.url if pull_request else None,
                pr_draft=pull_request.draft if pull_request else False,
                reused_pr=result.reused_pr,
                summary=change.summary if change else None,
                error=result.error,
                email_sent=result.email_sent,
                email_error=result.email_error,
                usage=change.usage if change else None,
                raw_log=(change.raw_log[-8000:] if change and change.raw_log else None),
                test_output=(tests.output[-8000:] if tests and tests.output else None),
                spec_diff=(diff.diff_text[:8000] if diff and diff.diff_text else None),
                judge_verdict=judge.verdict if judge else None,
                judge_reasoning=judge.reasoning if judge else None,
                judge_concerns=judge.concerns if judge else [],
                judge_criteria=judge.criteria if judge else [],
                attempts=result.attempts,
                jira_issue_key=result.jira_issue.key if result.jira_issue else None,
                jira_issue_url=result.jira_issue.url if result.jira_issue else None,
                jira_reused=result.jira_reused,
            )
        )
        return result

    try:
        page = await deps.confluence.fetch_page(page_id)
        progress["page"] = page

        allowed_labels = settings.confluence_allowed_labels_list
        if allowed_labels:
            page_labels = {label.lower() for label in page.labels}
            if not page_labels & set(allowed_labels):
                logger.info(
                    "Page %s labels %s don't include any of %s; ignoring.",
                    page_id,
                    sorted(page_labels),
                    allowed_labels,
                )
                return await finish(
                    PipelineResult(
                        status="ignored",
                        page=page,
                        error=f"Page has none of the required labels: {', '.join(allowed_labels)}",
                    )
                )

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
            return await finish(PipelineResult(status="no_change_detected", page=page, diff=diff))

        logger.info(
            "Detected change on page %s: v%s -> v%s", page_id, diff.previous_version, page.version
        )

        previous_page = deps.store.get(page_id)

        # Create the Jira story before any code is touched (the story is
        # about the spec change, not the eventual implementation -- see
        # jira/story_writer.py), so a subsequent failure anywhere downstream
        # still has a durable place to record what went wrong (see
        # _sync_jira_on_finish). If a story from a previous still-open run
        # for this page is still open, comment on it instead of creating a
        # duplicate -- mirrors the PR-branch reuse check below. Fails open
        # like every other external call here: a Jira outage never blocks
        # the rest of the pipeline.
        mark_stage("create_jira_story")
        if settings.jira_enabled and settings.jira_base_url and settings.jira_project_key:
            try:
                existing_key = previous_page.get("jira_issue_key") if previous_page else None
                if existing_key:
                    try:
                        existing_status = await deps.jira.get_issue_status(existing_key)
                        if existing_status.is_open:
                            jira_issue = JiraIssueResult(
                                key=existing_status.key,
                                url=f"{settings.jira_base_url.rstrip('/')}/browse/{existing_status.key}",
                            )
                            jira_reused = True
                    except Exception as exc:
                        logger.warning(
                            "Could not check status of existing Jira story %s for page %s; "
                            "creating a new one instead: %s",
                            existing_key, page_id, exc,
                        )

                if jira_issue is None:
                    story = await generate_story_content(settings, diff)
                    jira_issue = await deps.jira.create_issue(
                        project_key=settings.jira_project_key,
                        issue_type=settings.jira_issue_type,
                        summary=story.summary,
                        description=story.description,
                        acceptance_criteria=story.acceptance_criteria,
                    )
                    logger.info("Created Jira story %s for page %s", jira_issue.key, page_id)
                    # The raw spec diff as a follow-up comment, not part of
                    # the description -- the description is meant to be
                    # readable at a glance (prose, from an LLM when one's
                    # configured, or a short plain-English note when it
                    # isn't); a unified diff dumped into that same field
                    # defeats that regardless of which one produced it. This
                    # comment is where the exact technical detail lives.
                    if diff.is_first_seen:
                        diff_comment = f"Full current spec, as of v{page.version}:\n\n{diff.diff_text[:8000]}"
                    else:
                        diff_comment = (
                            f"Spec diff (v{diff.previous_version} -> v{page.version}):\n\n{diff.diff_text[:8000]}"
                        )
                    await deps.jira.add_comment(jira_issue.key, diff_comment)
                    if settings.jira_suggest_story_points and story.complexity:
                        await deps.jira.add_comment(
                            jira_issue.key,
                            f"AI-suggested complexity: {story.complexity} -- {story.complexity_reason}",
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to create/reuse a Jira story for page %s; continuing without one: %s", page_id, exc
                )
                jira_issue = None
                jira_reused = False

        repo_dir = settings.workdirs_path / f"page-{page_id}-v{page.version}"

        # If a PR from a previous run for this page is still open, reuse its
        # branch instead of opening a duplicate PR -- keeps one PR thread per
        # page for reviewers rather than fragmenting across several. Checked
        # fresh against the GitHub API every run (not assumed from the page
        # store's cache alone), since a human may have merged or closed it
        # since. Every step here fails open: any lookup/checkout problem
        # just falls back to today's default of a brand-new branch and PR.
        reuse_pr_number: int | None = None
        reuse_branch: str | None = None
        if previous_page and previous_page.get("open_pr_number") and previous_page.get("open_pr_branch"):
            try:
                pr_status = await deps.github.get_pull_request(settings.target_repo, previous_page["open_pr_number"])
                if pr_status.is_open:
                    reuse_pr_number = previous_page["open_pr_number"]
                    reuse_branch = previous_page["open_pr_branch"]
            except Exception as exc:
                logger.warning(
                    "Could not check status of previously-opened PR #%s for page %s; opening a new PR instead: %s",
                    previous_page["open_pr_number"], page_id, exc,
                )

        branch_name = reuse_branch or f"confluence-sync/page-{page_id}-v{page.version}-{int(time.time())}"

        mark_stage("clone_repo")
        await deps.git.clone(settings.target_repo, repo_dir, settings.target_repo_base_branch)
        if reuse_branch:
            try:
                await deps.git.checkout_existing_branch(repo_dir, branch_name)
                logger.info(
                    "PR #%s for page %s is still open; reusing its branch instead of opening a new PR.",
                    reuse_pr_number, page_id,
                )
            except Exception as exc:
                logger.warning(
                    "Could not check out existing PR branch %s for page %s; opening a new PR instead: %s",
                    branch_name, page_id, exc,
                )
                reuse_pr_number = None
                reuse_branch = None
                branch_name = f"confluence-sync/page-{page_id}-v{page.version}-{int(time.time())}"
                await deps.git.create_branch(repo_dir, branch_name)
        else:
            await deps.git.create_branch(repo_dir, branch_name)

        # Self-correction loop: give the change engine up to N attempts,
        # feeding the previous attempt's test failure back into its prompt
        # each retry, before giving up. Attempt 1 is today's original
        # behavior; CHANGE_AGENT_MAX_ATTEMPTS=1 disables retrying entirely.
        max_attempts = max(1, settings.change_agent_max_attempts)
        change: ChangeAgentResult | None = None
        tests = None
        retry_context: str | None = None

        for attempt in range(1, max_attempts + 1):
            mark_stage("ai_agent")
            change = await deps.change_engine.implement_change(
                repo_dir, diff, settings.change_agent_max_turns, retry_context=retry_context
            )

            if not change.success:
                logger.error(
                    "Change engine did not complete successfully for page %s (attempt %s/%s)",
                    page_id, attempt, max_attempts,
                )
                return await finish(
                    PipelineResult(
                        status="error", page=page, diff=diff, change=change, error="change agent failed",
                        attempts=attempt, jira_issue=jira_issue, jira_reused=jira_reused,
                    )
                )

            if not await deps.git.has_changes(repo_dir):
                logger.warning(
                    "Change agent made no file changes for page %s (attempt %s/%s)", page_id, attempt, max_attempts
                )
                return await finish(
                    PipelineResult(
                        status="error", page=page, diff=diff, change=change, error="agent made no file changes",
                        attempts=attempt, jira_issue=jira_issue, jira_reused=jira_reused,
                    )
                )

            change.files_changed = await deps.git.changed_files(repo_dir)

            mark_stage("run_tests")
            tests = await run_tests(repo_dir, settings.target_repo_test_command)
            if tests.passed:
                break

            if attempt == max_attempts:
                logger.error(
                    "Tests still failing for page %s after %s attempt(s); not opening a PR.", page_id, attempt
                )
                return await finish(
                    PipelineResult(
                        status="tests_failed", page=page, diff=diff, change=change, tests=tests, attempts=attempt,
                        jira_issue=jira_issue, jira_reused=jira_reused,
                    )
                )

            logger.warning(
                "Tests failed for page %s on attempt %s/%s; retrying with the failure fed back to the agent.",
                page_id, attempt, max_attempts,
            )
            retry_context = tests.output[-8000:]

        judge_result: JudgeResult | None = None
        if settings.judge_enabled:
            mark_stage("llm_judge")
            if not judge_configured(settings):
                judge_result = JudgeResult(
                    verdict="skipped",
                    reasoning=(
                        f"No API key configured for judge provider '{settings.judge_provider}'; "
                        "skipping LLM review."
                    ),
                )
                logger.info(
                    "Skipping LLM judge for page %s: no API key configured for provider '%s'.",
                    page_id,
                    settings.judge_provider,
                )
            else:
                try:
                    code_diff = await deps.git.diff(repo_dir)
                    judge_result = await deps.judge.evaluate(diff, change, code_diff)
                except Exception as exc:
                    # Fail open, same reasoning as the email step below: the
                    # judge is a second opinion, not the source of truth, so
                    # an unreliable API call must not turn an otherwise good
                    # change into a lost PR.
                    logger.warning(
                        "LLM judge failed for page %s; proceeding without review: %s", page_id, exc
                    )
                    judge_result = JudgeResult(
                        verdict="skipped", reasoning=f"Judge call failed; proceeding without review: {exc}"
                    )

            if judge_result.verdict == "rejected":
                logger.warning(
                    "LLM judge rejected the change for page %s: %s -- opening a flagged draft PR anyway.",
                    page_id, judge_result.reasoning,
                )

        # The judge is advisory, not a gate: a "rejected" verdict changes the
        # kind of PR that opens (draft, flagged title, "Needs review" callout
        # in the rubric) but never stops one from opening at all.
        is_rejected = judge_result is not None and judge_result.verdict == "rejected"

        mark_stage("open_pr")
        commit_message = f"Sync with Confluence spec: {page.title} (v{page.version})\n\n{change.summary}"
        await deps.git.commit_all(repo_dir, commit_message)

        pr_title = f"Sync with Confluence: {page.title} (v{page.version})"
        if is_rejected:
            pr_title = f"[Needs Work] {pr_title}"

        pr_body = _build_pr_body(page, diff, change, judge_result)
        verdict_for_labels = judge_result.verdict if judge_result else "approved"

        if reuse_branch:
            try:
                await deps.git.push(repo_dir, branch_name)
                pr_body = (
                    f"_Updated automatically: the spec changed again (v{diff.previous_version} -> "
                    f"v{page.version}) while this PR was still open, so it was updated in place "
                    "instead of opening a new one._\n\n"
                ) + pr_body
                pull_request = await deps.github.update_pull_request(
                    owner_repo=settings.target_repo, pr_number=reuse_pr_number, title=pr_title, body=pr_body,
                )
            except Exception as exc:
                # Unlike the lookup/checkout above, this can't fall back to
                # "just open a new PR instead" -- the agent's new commits are
                # already sitting on the existing branch. Surface it as a
                # normal error; retried from the same diff on the next
                # webhook, same as any other push/API failure.
                logger.exception("Failed to update existing PR #%s for page %s", reuse_pr_number, page_id)
                return await finish(
                    PipelineResult(
                        status="error", page=page, diff=diff, change=change, tests=tests,
                        error=f"failed to update existing PR #{reuse_pr_number}: {exc}", attempts=attempt,
                        jira_issue=jira_issue, jira_reused=jira_reused,
                    )
                )
        else:
            await deps.git.push(repo_dir, branch_name)
            pull_request = await deps.github.open_pull_request(
                owner_repo=settings.target_repo,
                head_branch=branch_name,
                base_branch=settings.target_repo_base_branch,
                title=pr_title,
                body=pr_body,
                draft=is_rejected,
            )

        await _sync_verdict_label(deps.github, settings.target_repo, pull_request.number, verdict_for_labels)

        # A durable artifact (the PR) now exists for this diff either way,
        # so the store advances regardless of the judge's verdict -- a retry
        # from the same diff on the next webhook would otherwise open a
        # second, duplicate PR alongside this one. Tracking the PR here is
        # also what makes the *next* run's reuse check possible.
        deps.store.put(
            StoredPage(
                page_id=page.page_id,
                title=page.title,
                version=page.version,
                body_html=page.body_html,
                body_checksum=diff.body_checksum,
                url=page.url,
                open_pr_number=pull_request.number,
                open_pr_branch=pull_request.branch,
                jira_issue_key=jira_issue.key if jira_issue else None,
            )
        )

        if is_rejected:
            logger.info(
                "%s flagged draft PR #%s for page %s: %s",
                "Updated" if reuse_branch else "Opened", pull_request.number, page_id, pull_request.url,
            )
            return await finish(
                PipelineResult(
                    status="judge_rejected",
                    page=page,
                    diff=diff,
                    change=change,
                    tests=tests,
                    judge=judge_result,
                    pull_request=pull_request,
                    reused_pr=bool(reuse_branch),
                    attempts=attempt,
                    jira_issue=jira_issue,
                    jira_reused=jira_reused,
                )
            )

        # Best-effort and deliberately isolated: the PR is already open at
        # this point, so a broken/unconfigured email step must not turn a
        # successful run into a reported failure (it did, before this was
        # fixed -- a blank SENDGRID_API_KEY produced an unhandled
        # httpx.LocalProtocolError here that the outer `except` caught,
        # discarding the pull_request from the recorded result entirely).
        mark_stage("send_email")
        email_sent = False
        email_error: str | None = None
        email_key = settings.postmark_api_key if settings.email_provider.strip().lower() == "postmark" else settings.sendgrid_api_key
        if not email_key:
            email_error = f"No API key configured for email provider '{settings.email_provider}'; skipped"
            logger.info("Skipping summary email for PR #%s: %s", pull_request.number, email_error)
        else:
            try:
                subject, text_body, html_body = build_summary_email(diff, change, pull_request)
                await deps.email_client.send_email(
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

        logger.info(
            "%s PR #%s for page %s: %s",
            "Updated" if reuse_branch else "Opened", pull_request.number, page_id, pull_request.url,
        )
        return await finish(
            PipelineResult(
                status="opened_pr",
                page=page,
                diff=diff,
                change=change,
                tests=tests,
                judge=judge_result,
                pull_request=pull_request,
                reused_pr=bool(reuse_branch),
                email_sent=email_sent,
                email_error=email_error,
                attempts=attempt,
                jira_issue=jira_issue,
                jira_reused=jira_reused,
            )
        )

    except Exception as exc:
        logger.exception("Pipeline failed for page %s", page_id)
        return await finish(PipelineResult(status="error", error=str(exc), jira_issue=jira_issue, jira_reused=jira_reused))
    finally:
        if owns_deps:
            await deps.confluence.aclose()
            await deps.github.aclose()
            await deps.email_client.aclose()
