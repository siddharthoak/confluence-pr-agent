"""Jira Cloud REST API client -- create/comment/check-status on the story
tracking a page's spec change. Mirrors repo/github_client.py's shape (plain
httpx, Basic Auth), not the `jira` PyPI package -- this project doesn't
depend on it, and the REST surface needed here is small enough not to.
"""

from __future__ import annotations

import httpx

from confluence_pr_agent.jira.adf import build_story_description_adf, text_to_adf
from confluence_pr_agent.models import JiraIssueResult, JiraIssueStatus

API_VERSION = "3"


class JiraClient:
    """`base_url` is the site root, e.g. https://your-team.atlassian.net --
    no /wiki suffix (that's Confluence-specific; Jira Cloud's REST API and
    browse URLs both live at the site root).
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

    def _issue_url(self, key: str) -> str:
        return f"{self._base_url}/browse/{key}"

    async def create_issue(
        self,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str,
        acceptance_criteria: list[str] | None = None,
    ) -> JiraIssueResult:
        resp = await self._client.post(
            f"{self._base_url}/rest/api/{API_VERSION}/issue",
            auth=self._auth,
            json={
                "fields": {
                    "project": {"key": project_key},
                    "issuetype": {"name": issue_type},
                    "summary": summary,
                    "description": build_story_description_adf(description, acceptance_criteria or []),
                }
            },
        )
        resp.raise_for_status()
        key = resp.json()["key"]
        return JiraIssueResult(key=key, url=self._issue_url(key))

    async def add_comment(self, issue_key: str, comment: str) -> None:
        resp = await self._client.post(
            f"{self._base_url}/rest/api/{API_VERSION}/issue/{issue_key}/comment",
            auth=self._auth,
            json={"body": text_to_adf(comment)},
        )
        resp.raise_for_status()

    async def get_issue_status(self, issue_key: str) -> JiraIssueStatus:
        """Fetched fresh each run (not trusted from the page store's cached
        jira_issue_key alone) so a story someone closed/completed is always
        detected before deciding whether to reuse it.
        """
        resp = await self._client.get(
            f"{self._base_url}/rest/api/{API_VERSION}/issue/{issue_key}",
            auth=self._auth,
            params={"fields": "status"},
        )
        resp.raise_for_status()
        data = resp.json()
        status = data["fields"]["status"]
        return JiraIssueStatus(
            key=data["key"], status_name=status["name"], status_category=status["statusCategory"]["key"]
        )
