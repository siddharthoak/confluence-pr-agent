from __future__ import annotations

from confluence_pr_agent.confluence.diff import _to_plain_text, compute_checksum, compute_diff
from confluence_pr_agent.models import PageSnapshot
from confluence_pr_agent.storage.page_store import PageStore, StoredPage


def _page(version: int, body: str) -> PageSnapshot:
    return PageSnapshot(
        page_id="123456",
        title="Checkout Flow Spec",
        version=version,
        body_html=body,
        url="https://example.atlassian.net/wiki/spaces/SD/pages/123456",
    )


def _checksum_for(body_html: str) -> str:
    return compute_checksum(_to_plain_text(body_html))


def _stored(version: int, body_html: str) -> StoredPage:
    return StoredPage(
        page_id="123456",
        title="Checkout Flow Spec",
        version=version,
        body_html=body_html,
        body_checksum=_checksum_for(body_html),
        url="https://example.com",
    )


def test_first_seen_page_has_no_previous_version(tmp_path):
    store = PageStore(tmp_path / "store.json")
    page = _page(1, "<p>Checkout must support credit card payments.</p>")

    diff = compute_diff(store, page)

    assert diff.is_first_seen is True
    assert diff.previous_version is None
    assert "credit card" in diff.diff_text
    assert diff.body_checksum == _checksum_for(page.body_html)


def test_unchanged_version_produces_empty_diff(tmp_path):
    """Redelivering the same webhook for a page that hasn't moved is a no-op."""
    store = PageStore(tmp_path / "store.json")
    store.put(_stored(1, "<p>Checkout must support credit card payments.</p>"))
    page = _page(1, "<p>Checkout must support credit card payments.</p>")

    diff = compute_diff(store, page)

    assert diff.is_first_seen is False
    assert diff.diff_text == ""
    assert diff.content_unchanged is False  # short-circuited on version match, not checksum


def test_changed_version_produces_unified_diff(tmp_path):
    store = PageStore(tmp_path / "store.json")
    store.put(_stored(1, "<p>Checkout must support credit card payments.</p>"))
    page = _page(2, "<p>Checkout must support credit card and PayPal payments.</p>")

    diff = compute_diff(store, page)

    assert diff.is_first_seen is False
    assert diff.previous_version == 1
    assert "PayPal" in diff.diff_text
    assert diff.diff_text.startswith("---")


def test_version_bump_with_identical_content_is_treated_as_no_change(tmp_path):
    """A metadata-only edit (labels, restrictions, a no-op restore) bumps the
    version without changing the visible body -- the checksum guard should
    catch this and skip the pipeline, same as an exact version match.
    """
    store = PageStore(tmp_path / "store.json")
    body_html = "<p>Checkout must support credit card payments.</p>"
    store.put(_stored(1, body_html))
    page = _page(2, body_html)  # version moved, content did not

    diff = compute_diff(store, page)

    assert diff.is_first_seen is False
    assert diff.previous_version == 1
    assert diff.diff_text == ""
    assert diff.content_unchanged is True


def test_checksum_ignores_insignificant_html_differences(tmp_path):
    """Whitespace/formatting-only storage-format differences that normalize
    to the same plain text should also be treated as no change.
    """
    store = PageStore(tmp_path / "store.json")
    store.put(_stored(1, "<p>Checkout must support credit card payments.</p>"))
    page = _page(2, "<p>  Checkout must support credit card payments.  </p>")

    diff = compute_diff(store, page)

    assert diff.diff_text == ""
    assert diff.content_unchanged is True
