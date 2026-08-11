"""Parsing helpers for Confluence's webhook payload.

Confluence Cloud webhook payload shape varies depending on how the webhook
was registered (classic space webhook vs. a Connect/Forge app webhook), so
rather than binding to one exact schema we check the handful of common
locations a page id shows up in.
"""

from __future__ import annotations

from typing import Any


def extract_page_id(payload: dict[str, Any]) -> str | None:
    page = payload.get("page")
    if isinstance(page, dict) and page.get("id"):
        return str(page["id"])

    content = payload.get("content")
    if isinstance(content, dict) and content.get("id"):
        return str(content["id"])

    if payload.get("pageId"):
        return str(payload["pageId"])

    return None


def extract_event_type(payload: dict[str, Any]) -> str | None:
    for key in ("event", "eventType", "webhookEvent"):
        value = payload.get(key)
        if value:
            return str(value)
    return None
