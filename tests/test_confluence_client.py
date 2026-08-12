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
    assert page.labels == []  # fixture has no metadata.labels -- must not error, just be empty


@respx.mock
async def test_fetch_page_requests_and_parses_labels():
    response_json = {
        "id": "123456",
        "title": "Checkout Flow Spec",
        "version": {"number": 3},
        "body": {"storage": {"value": "<p>Checkout must support credit card payments.</p>"}},
        "_links": {"webui": "/spaces/SD/pages/123456/Checkout+Flow+Spec"},
        "metadata": {
            "labels": {
                "results": [
                    {"prefix": "global", "name": "brd", "id": "1", "label": "brd"},
                    {"prefix": "global", "name": "checkout", "id": "2", "label": "checkout"},
                ],
                "size": 2,
            }
        },
    }
    route = respx.get("https://neurealm-team-juadifpx.atlassian.net/wiki/rest/api/content/123456").mock(
        return_value=httpx.Response(200, json=response_json)
    )

    client = ConfluenceClient(
        base_url="https://neurealm-team-juadifpx.atlassian.net/wiki",
        email="test@example.com",
        api_token="token",
    )
    page = await client.fetch_page("123456")
    await client.aclose()

    assert page.labels == ["brd", "checkout"]
    # confirms the client asks for labels in the same request (no second API call)
    assert "metadata.labels" in route.calls.last.request.url.params["expand"]


@respx.mock
async def test_search_page_ids_filters_by_space_and_label():
    route = respx.get("https://neurealm-team-juadifpx.atlassian.net/wiki/rest/api/content/search").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": "111"}, {"id": "222"}], "_links": {}}
        )
    )

    client = ConfluenceClient(
        base_url="https://neurealm-team-juadifpx.atlassian.net/wiki",
        email="test@example.com",
        api_token="token",
    )
    page_ids = await client.search_page_ids("SD", ["brd", "spec-for-agent"])
    await client.aclose()

    assert page_ids == ["111", "222"]
    cql = route.calls.last.request.url.params["cql"]
    assert 'space="SD"' in cql
    assert 'label="brd"' in cql
    assert 'label="spec-for-agent"' in cql


@respx.mock
async def test_search_page_ids_with_no_labels_has_no_label_filter():
    route = respx.get("https://neurealm-team-juadifpx.atlassian.net/wiki/rest/api/content/search").mock(
        return_value=httpx.Response(200, json={"results": [], "_links": {}})
    )

    client = ConfluenceClient(
        base_url="https://neurealm-team-juadifpx.atlassian.net/wiki",
        email="test@example.com",
        api_token="token",
    )
    await client.search_page_ids("SD", [])
    await client.aclose()

    assert "label=" not in route.calls.last.request.url.params["cql"]


@respx.mock
async def test_search_page_ids_follows_pagination_links():
    respx.get(
        "https://neurealm-team-juadifpx.atlassian.net/wiki/rest/api/content/search",
        params={"cql": 'space="SD" AND type=page', "limit": "100"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "1"}],
                "_links": {"next": "/rest/api/content/search?cql=space%3D%22SD%22&start=1&limit=100"},
            },
        )
    )
    respx.get(
        "https://neurealm-team-juadifpx.atlassian.net/wiki/rest/api/content/search",
        params={"cql": 'space="SD"', "start": "1", "limit": "100"},
    ).mock(return_value=httpx.Response(200, json={"results": [{"id": "2"}], "_links": {}}))

    client = ConfluenceClient(
        base_url="https://neurealm-team-juadifpx.atlassian.net/wiki",
        email="test@example.com",
        api_token="token",
    )
    page_ids = await client.search_page_ids("SD", [])
    await client.aclose()

    assert page_ids == ["1", "2"]
