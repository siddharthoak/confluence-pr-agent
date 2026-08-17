"""Prompt text shared by every ChangeEngine implementation."""

from __future__ import annotations

from pathlib import Path

from confluence_pr_agent.models import PageDiff, RepoTarget

SYSTEM_PROMPT = """You are a senior software engineer implementing a change to a codebase based \
on an updated feature specification from Confluence. Rules:

1. Read enough of the existing repo to understand its structure and conventions before editing.
2. Implement the minimal, correct code change that satisfies the updated spec.
3. Add or update unit/integration tests that cover the change -- this is required, not optional.
4. Do not perform unrelated refactors or touch files outside the scope of the change.
5. Your final message must be a concise 3-6 sentence summary of exactly what you changed and \
why, written so it can be pasted directly into a pull request description.
"""


def build_repo_context(repo_targets: list[RepoTarget], repo_dirs: dict[str, Path], workspace: Path) -> str:
    """Describes which repos are checked out as which subdirectories of the
    agent's working directory, for a genuinely multi-repo run -- see
    PageDiff.repo_context. `repo_targets` is the in-scope list (already
    filtered by pipeline/orchestrator.py's label-routing check), each
    entry's cloned path looked up in `repo_dirs`.
    """
    lines = [
        "This change may span more than one repo, each checked out as a subdirectory "
        "of your working directory:",
        "",
    ]
    for rt in repo_targets:
        rel = repo_dirs[rt.target_repo].relative_to(workspace)
        lines.append(f"- `{rel}/` -- {rt.target_repo}")
    lines.append(
        "\nOnly edit the repos actually relevant to this change -- leave the others untouched. "
        "If a change in one repo depends on another (e.g. an interface one repo exposes and "
        "another calls), make sure the edits across them stay consistent with each other."
    )
    return "\n".join(lines)


def build_user_prompt(diff: PageDiff, retry_context: str | None = None) -> str:
    header = (
        f"Confluence spec page: {diff.page.title}\n"
        f"Page URL: {diff.page.url}\n"
        f"Page version: {diff.previous_version} -> {diff.page.version}\n\n"
    )
    if diff.repo_context:
        header += diff.repo_context + "\n\n"
    if diff.is_first_seen:
        body = (
            "This is the first time this page has been processed. Implement the feature "
            "described below to the extent it is not already implemented in this repo.\n\n"
            + diff.diff_text
        )
    else:
        body = (
            "The spec changed as shown below (unified diff of the page's plain-text content). "
            "Implement the corresponding code change:\n\n" + diff.diff_text
        )
    if retry_context:
        body += (
            "\n\n---\n\nYour previous attempt at this same change left the repo's test suite "
            "failing. The working directory already has your previous edits in it -- fix them "
            "in place rather than starting over from scratch, unless the failure output below "
            "makes clear the previous approach was fundamentally wrong. Previous test output:\n\n"
            + retry_context
        )
    return header + body


def build_combined_prompt(diff: PageDiff, retry_context: str | None = None) -> str:
    """For CLIs with no separate system-prompt channel: system + user prompt as one string."""
    return f"{SYSTEM_PROMPT}\n\n---\n\n{build_user_prompt(diff, retry_context)}"
