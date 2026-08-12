from __future__ import annotations

import json

import httpx
import respx

from confluence_pr_agent.notifications.postmark_client import PostmarkClient


@respx.mock
async def test_send_email_posts_expected_payload():
    route = respx.post("https://api.postmarkapp.com/email").mock(
        return_value=httpx.Response(200, json={"ErrorCode": 0, "Message": "OK"})
    )

    client = PostmarkClient(server_token="test-token")
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
    assert request.headers["x-postmark-server-token"] == "test-token"

    payload = json.loads(request.content)
    assert payload["Subject"] == "Subject"
    assert payload["From"] == "agent@example.com"
    assert payload["To"] == "team@example.com, lead@example.com"
    assert payload["TextBody"] == "text"
    assert payload["HtmlBody"] == "<p>html</p>"


@respx.mock
async def test_send_email_raises_on_error_response():
    respx.post("https://api.postmarkapp.com/email").mock(
        return_value=httpx.Response(422, json={"ErrorCode": 300, "Message": "Invalid email"})
    )

    client = PostmarkClient(server_token="test-token")
    try:
        raised = False
        try:
            await client.send_email(
                from_address="bad", to_addresses=["team@example.com"], subject="s", text_body="t", html_body="h"
            )
        except httpx.HTTPStatusError:
            raised = True
        assert raised
    finally:
        await client.aclose()
