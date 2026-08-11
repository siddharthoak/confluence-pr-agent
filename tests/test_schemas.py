from __future__ import annotations

from confluence_pr_agent.webhook.schemas import extract_event_type, extract_page_id


def test_extract_page_id_from_page_key():
    assert extract_page_id({"page": {"id": "123"}}) == "123"


def test_extract_page_id_from_content_key():
    assert extract_page_id({"content": {"id": "456"}}) == "456"


def test_extract_page_id_from_flat_key():
    assert extract_page_id({"pageId": 789}) == "789"


def test_extract_page_id_returns_none_when_absent():
    assert extract_page_id({}) is None


def test_extract_event_type_checks_known_keys():
    assert extract_event_type({"event": "page_updated"}) == "page_updated"
    assert extract_event_type({"webhookEvent": "page_updated"}) == "page_updated"
    assert extract_event_type({}) is None
