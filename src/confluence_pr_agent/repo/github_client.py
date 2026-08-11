"""GitHub REST API client for opening pull requests.

Branch creation/commit/push is handled by `git_client.GitClient`; this talks
to the GitHub REST API (plain HTTP via httpx) purely to open the PR itself.
"""

from __future__ import annotations

import httpx

from confluence_pr_agent.models import PullRequestResult

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client or httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def open_pull_request(
        self,
        owner_repo: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> PullRequestResult:
        resp = await self._client.post(
            f"/repos/{owner_repo}/pulls",
            json={"title": title, "head": head_branch, "base": base_branch, "body": body},
        )
        resp.raise_for_status()
        data = resp.json()
        return PullRequestResult(number=data["number"], url=data["html_url"], branch=head_branch)
