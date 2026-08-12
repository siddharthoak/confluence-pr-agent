from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from confluence_pr_agent.config import get_process_config, get_settings
from confluence_pr_agent.webhook import app as webhook_app_module


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """/webhook/confluence always resolves the bootstrap/default user's
    Settings (see webhook/app.py -- a raw webhook delivery has no
    Caddy-authenticated identity attached to it), so DEFAULT_USER needs to
    be set even though these tests never touch a /ui/* route. Same
    DATA_DIR isolation as test_ui.py, for the same reason: otherwise these
    tests would read/write the real project's live data/users/*/ state.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DEFAULT_USER", "testuser")
    monkeypatch.setenv("INTERNAL_SHARED_SECRET", "")
    get_process_config.cache_clear()
    get_settings.cache_clear()
    yield
    get_process_config.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def stub_pipeline(monkeypatch):
    calls: list[str] = []

    async def _fake_run_pipeline(page_id, deps=None):
        calls.append(page_id)

    monkeypatch.setattr(webhook_app_module, "run_pipeline", _fake_run_pipeline)
    return calls


def test_healthz():
    client = TestClient(webhook_app_module.app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_root_redirects_to_ui():
    """No route existed for the bare "/" before -- a successful Caddy Basic
    Auth login (its catch-all handle block covers "/" too) landed on a 404
    with nothing else to do."""
    client = TestClient(webhook_app_module.app, follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/ui"


def test_webhook_accepts_valid_payload(stub_pipeline, load_fixture):
    client = TestClient(webhook_app_module.app)
    payload = load_fixture("confluence_webhook_payload.json")

    resp = client.post("/webhook/confluence", json=payload)

    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted", "page_id": "123456"}
    assert stub_pipeline == ["123456"]


def test_webhook_rejects_payload_without_page_id(stub_pipeline):
    client = TestClient(webhook_app_module.app)

    resp = client.post("/webhook/confluence", json={"event": "page_updated"})

    assert resp.status_code == 400
    assert stub_pipeline == []


def test_webhook_verifies_signature_when_secret_configured(stub_pipeline, load_fixture):
    # Settings no longer reads os.environ at all (see config.py) -- the
    # secret has to be written to the bootstrap user's own .env file, not
    # set via monkeypatch.setenv.
    process = get_process_config()
    process.user_env_path(process.resolved_default_user).write_text("CONFLUENCE_WEBHOOK_SECRET=shh\n")
    get_settings.cache_clear()

    client = TestClient(webhook_app_module.app)
    payload = load_fixture("confluence_webhook_payload.json")
    body = json.dumps(payload).encode()

    resp = client.post(
        "/webhook/confluence",
        content=body,
        headers={"content-type": "application/json", "x-hub-signature-256": "sha256=deadbeef"},
    )
    assert resp.status_code == 401

    signature = hmac.new(b"shh", body, hashlib.sha256).hexdigest()
    resp = client.post(
        "/webhook/confluence",
        content=body,
        headers={"content-type": "application/json", "x-hub-signature-256": f"sha256={signature}"},
    )
    assert resp.status_code == 200
    assert stub_pipeline == ["123456"]
