from __future__ import annotations

import httpx
import respx

from confluence_pr_agent.confluence.client import ConfluenceClient


@respx.mock
async def test_fetch_page_parses_response(load_fixture):
    fixture = load_fixture("confluence_page_v1.json")
    respx.get(
        "https://neurealm-team-juadifpx.atlassian.net/wiki/rest/api/content/123456"
    ).mock(return_value=httpx.Response(200, json=fixture))

    client = ConfluenceClient(
        base_url="https://neurealm-team-juadifpx.atlassian.net/wiki",
        email="test@example.com",
        api_token="token",
    )
    page = await client.fetch_page("123456")
    await client.aclose()

    assert page.page_id == "123456"
    assert page.version == 1
    assert "credit card" in page.body_html
    assert page.url == (
        "https://neurealm-team-juadifpx.atlassian.net/wiki"
        "/spaces/SD/pages/123456/Checkout+Flow+Spec"
    )
