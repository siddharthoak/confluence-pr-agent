"""Diffs the current page body against the last-seen version in the PageStore.

Two independent guards keep a redelivered/no-op webhook from triggering a
real pipeline run (clone + change engine + tests + PR):

1. Version check: if the fetched version equals the stored version, this is
   a duplicate delivery of an already-processed page -- bail immediately,
   before even looking at content.
2. Checksum check: Confluence bumps the version number on some edits that
   don't change the visible body (e.g. labels, restrictions, a no-op
   "restore this version"). If the version moved but the sha256 of the
   normalized plain-text body matches what we last processed, treat it the
   same as no change -- skips the (more expensive) diff computation too.
"""

from __future__ import annotations

import difflib
import hashlib
import re

from confluence_pr_agent.models import PageDiff, PageSnapshot
from confluence_pr_agent.storage.page_store import PageStore

_BLOCK_TAGS = re.compile(r"</?(p|div|h[1-6]|li|ul|ol|table|tr|br)\b[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")


def _to_plain_text(storage_html: str) -> str:
    """Best-effort conversion of Confluence storage-format XHTML to plain text.

    Not a full parser -- good enough to produce a readable diff for the change
    agent's prompt, not to reconstruct exact markup.
    """
    text = _BLOCK_TAGS.sub("\n", storage_html)
    text = _ANY_TAG.sub("", text)
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def compute_checksum(plain_text: str) -> str:
    return hashlib.sha256(plain_text.encode("utf-8")).hexdigest()


def compute_diff(store: PageStore, page: PageSnapshot) -> PageDiff:
    previous = store.get(page.page_id)
    new_text = _to_plain_text(page.body_html)
    new_checksum = compute_checksum(new_text)

    if previous is None:
        diff_text = (
            "(No prior version on record for this page -- treating the full "
            "current body as the initial spec.)\n\n" + new_text
        )
        return PageDiff(
            page=page,
            previous_version=None,
            diff_text=diff_text,
            is_first_seen=True,
            body_checksum=new_checksum,
        )

    if previous["version"] == page.version:
        return PageDiff(
            page=page,
            previous_version=previous["version"],
            diff_text="",
            is_first_seen=False,
            body_checksum=new_checksum,
        )

    previous_checksum = previous.get("body_checksum", "")
    if previous_checksum and previous_checksum == new_checksum:
        return PageDiff(
            page=page,
            previous_version=previous["version"],
            diff_text="",
            is_first_seen=False,
            body_checksum=new_checksum,
            content_unchanged=True,
        )

    old_text = _to_plain_text(previous["body_html"])
    diff_lines = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"{page.title} (v{previous['version']})",
        tofile=f"{page.title} (v{page.version})",
    )
    diff_text = "".join(diff_lines)

    return PageDiff(
        page=page,
        previous_version=previous["version"],
        diff_text=diff_text,
        is_first_seen=False,
        body_checksum=new_checksum,
    )
