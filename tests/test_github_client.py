from __future__ import annotations

import httpx
import respx

from confluence_pr_agent.repo.github_client import GitHubClient


@respx.mock
async def test_open_pull_request_returns_result():
    respx.post("https://api.github.com/repos/acme/widgets/pulls").mock(
        return_value=httpx.Response(
            201, json={"number": 42, "html_url": "https://github.com/acme/widgets/pull/42"}
        )
    )

    client = GitHubClient(token="test-token")
    result = await client.open_pull_request(
        owner_repo="acme/widgets",
        head_branch="confluence-sync/page-1-v2",
        base_branch="main",
        title="Sync with Confluence",
        body="body",
    )
    await client.aclose()

    assert result.number == 42
    assert result.url == "https://github.com/acme/widgets/pull/42"
    assert result.branch == "confluence-sync/page-1-v2"
