from __future__ import annotations

from confluence_pr_agent.models import RunRecord
from confluence_pr_agent.storage.run_store import RunStore


def _record(run_id: str, **overrides) -> RunRecord:
    defaults = dict(
        run_id=run_id,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:05+00:00",
        duration_seconds=5.0,
        page_id="1",
        page_title="Spec",
        confluence_url="https://example.com",
        engine="claude_code",
        target_repo="acme/widgets",
        status="opened_pr",
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


def test_delete_run_removes_matching_record(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    store.add_run(_record("a"))
    store.add_run(_record("b"))

    deleted = store.delete_run("a")

    assert deleted is True
    remaining_ids = [r["run_id"] for r in store.list_runs()]
    assert remaining_ids == ["b"]


def test_delete_run_returns_false_for_unknown_id(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    store.add_run(_record("a"))

    assert store.delete_run("does-not-exist") is False
    assert len(store.list_runs()) == 1


def test_clear_all_removes_every_record(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    store.add_run(_record("a"))
    store.add_run(_record("b"))

    store.clear_all()

    assert store.list_runs() == []


def test_upsert_run_inserts_when_run_id_is_new(tmp_path):
    store = RunStore(tmp_path / "runs.json")

    store.upsert_run(_record("a", status="running"))

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "running"


def test_upsert_run_replaces_existing_record_in_place(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    store.add_run(_record("a", status="running"))
    store.add_run(_record("b", status="opened_pr"))

    store.upsert_run(_record("a", status="opened_pr", pr_number=5))

    runs = store.list_runs()
    assert len(runs) == 2  # no duplicate row for "a"
    a = next(r for r in runs if r["run_id"] == "a")
    assert a["status"] == "opened_pr"
    assert a["pr_number"] == 5
