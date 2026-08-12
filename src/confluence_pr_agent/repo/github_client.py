"""GitHub REST API client for opening/updating pull requests and their
labels.

Branch creation/commit/push is handled by `git_client.GitClient`; this talks
to the GitHub REST API (plain HTTP via httpx) for everything PR-shaped.
"""

from __future__ import annotations

import httpx

from confluence_pr_agent.models import PullRequestResult, PullRequestStatus

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
        draft: bool = False,
    ) -> PullRequestResult:
        resp = await self._client.post(
            f"/repos/{owner_repo}/pulls",
            json={"title": title, "head": head_branch, "base": base_branch, "body": body, "draft": draft},
        )
        resp.raise_for_status()
        data = resp.json()
        return PullRequestResult(number=data["number"], url=data["html_url"], branch=head_branch, draft=data.get("draft", draft))

    async def get_pull_request(self, owner_repo: str, pr_number: int) -> PullRequestStatus:
        """Fetched fresh each run (not trusted from the page store's cached
        open_pr_number alone) so a PR merged or closed by a human is always
        detected before deciding whether to reuse its branch.
        """
        resp = await self._client.get(f"/repos/{owner_repo}/pulls/{pr_number}")
        resp.raise_for_status()
        data = resp.json()
        return PullRequestStatus(number=data["number"], state=data["state"], merged=bool(data.get("merged", False)))

    async def update_pull_request(self, owner_repo: str, pr_number: int, title: str, body: str) -> PullRequestResult:
        resp = await self._client.patch(f"/repos/{owner_repo}/pulls/{pr_number}", json={"title": title, "body": body})
        resp.raise_for_status()
        data = resp.json()
        return PullRequestResult(
            number=data["number"], url=data["html_url"], branch=data["head"]["ref"], draft=data.get("draft", False)
        )

    async def ensure_label(self, owner_repo: str, name: str, color: str, description: str = "") -> None:
        """Creates the label if the repo doesn't already have it. GitHub's
        "add labels to an issue" endpoint 404s on a label name that doesn't
        exist in the repo yet, so this has to run before the first time a
        label is actually applied -- a 422 here just means it already
        exists, which is the common case after the first call.
        """
        resp = await self._client.post(
            f"/repos/{owner_repo}/labels", json={"name": name, "color": color, "description": description}
        )
        if resp.status_code == 422:
            return
        resp.raise_for_status()

    async def add_labels(self, owner_repo: str, pr_number: int, labels: list[str]) -> None:
        if not labels:
            return
        resp = await self._client.post(f"/repos/{owner_repo}/issues/{pr_number}/labels", json={"labels": labels})
        resp.raise_for_status()

    async def remove_label(self, owner_repo: str, pr_number: int, label: str) -> None:
        resp = await self._client.delete(f"/repos/{owner_repo}/issues/{pr_number}/labels/{label}")
        if resp.status_code == 404:
            return  # wasn't on the PR (or repo) -- already the desired state
        resp.raise_for_status()
