from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from confluence_pr_agent.config import get_settings
from confluence_pr_agent.webhook import app as webhook_app_module


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
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


def test_webhook_verifies_signature_when_secret_configured(stub_pipeline, monkeypatch, load_fixture):
    monkeypatch.setenv("CONFLUENCE_WEBHOOK_SECRET", "shh")
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
