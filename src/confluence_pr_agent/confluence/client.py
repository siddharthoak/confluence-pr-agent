"""Confluence Cloud REST API client."""

from __future__ import annotations

import httpx

from confluence_pr_agent.models import PageSnapshot


class ConfluenceClient:
    """Thin wrapper around the Confluence Cloud content API.

    `base_url` should be the site's `/wiki` root, e.g.
    https://your-team.atlassian.net/wiki
    """

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(email, api_token)
        self._client = http_client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_page(self, page_id: str) -> PageSnapshot:
        """Fetch the current storage-format body + version for a page."""
        resp = await self._client.get(
            f"{self._base_url}/rest/api/content/{page_id}",
            params={"expand": "body.storage,version"},
            auth=self._auth,
        )
        resp.raise_for_status()
        data = resp.json()

        body_html = data["body"]["storage"]["value"]
        version = data["version"]["number"]
        title = data["title"]
        webui_path = data.get("_links", {}).get("webui", f"/pages/{data['id']}")
        page_url = f"{self._base_url}{webui_path}"

        return PageSnapshot(
            page_id=str(data["id"]),
            title=title,
            version=version,
            body_html=body_html,
            url=page_url,
        )
