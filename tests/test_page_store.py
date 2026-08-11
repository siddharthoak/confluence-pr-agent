from __future__ import annotations

from confluence_pr_agent.storage.page_store import PageStore, StoredPage


def test_get_returns_none_when_absent(tmp_path):
    store = PageStore(tmp_path / "store.json")
    assert store.get("123") is None


def test_put_then_get_roundtrips(tmp_path):
    store = PageStore(tmp_path / "store.json")
    page = StoredPage(
        page_id="123", title="Spec", version=1, body_html="<p>hi</p>", body_checksum="abc123", url="https://x"
    )
    store.put(page)

    assert store.get("123") == page


def test_persists_across_instances(tmp_path):
    path = tmp_path / "store.json"
    store1 = PageStore(path)
    store1.put(
        StoredPage(
            page_id="123", title="Spec", version=1, body_html="<p>hi</p>", body_checksum="abc123", url="https://x"
        )
    )

    store2 = PageStore(path)
    stored = store2.get("123")
    assert stored is not None
    assert stored["version"] == 1
