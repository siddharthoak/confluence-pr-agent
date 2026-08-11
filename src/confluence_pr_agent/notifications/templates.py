"""Builds the team notification email content."""

from __future__ import annotations

from confluence_pr_agent.models import ChangeAgentResult, PageDiff, PullRequestResult


def build_summary_email(
    diff: PageDiff,
    change: ChangeAgentResult,
    pull_request: PullRequestResult,
) -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body)."""
    subject = f"[confluence-pr-agent] PR #{pull_request.number}: {diff.page.title}"

    text_body = (
        f'The spec page "{diff.page.title}" changed and a pull request was opened.\n\n'
        f"Confluence page: {diff.page.url}\n"
        f"Pull request: {pull_request.url}\n\n"
        f"Summary of the change:\n{change.summary}\n"
    )

    html_body = (
        f"<p>The spec page <strong>{diff.page.title}</strong> changed and a pull request "
        "was opened.</p>"
        "<ul>"
        f'<li>Confluence page: <a href="{diff.page.url}">{diff.page.url}</a></li>'
        f'<li>Pull request: <a href="{pull_request.url}">{pull_request.url}</a></li>'
        "</ul>"
        "<p><strong>Summary of the change:</strong></p>"
        f"<p>{change.summary}</p>"
    )

    return subject, text_body, html_body
