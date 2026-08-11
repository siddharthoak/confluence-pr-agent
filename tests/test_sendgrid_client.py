from __future__ import annotations

import json

import httpx
import respx

from confluence_pr_agent.notifications.sendgrid_client import SendGridClient


@respx.mock
async def test_send_email_posts_expected_payload():
    route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(return_value=httpx.Response(202))

    client = SendGridClient(api_key="test-key")
    await client.send_email(
        from_address="agent@example.com",
        to_addresses=["team@example.com", "lead@example.com"],
        subject="Subject",
        text_body="text",
        html_body="<p>html</p>",
    )
    await client.aclose()

    assert route.called
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-key"

    payload = json.loads(request.content)
    assert payload["subject"] == "Subject"
    assert payload["from"] == {"email": "agent@example.com"}
    assert len(payload["personalizations"][0]["to"]) == 2
