"""Postmark HTTP API client for the post-PR team notification email.

Same interface as notifications/sendgrid_client.py::SendGridClient -- pick
one via EMAIL_PROVIDER (config.py), not both.
"""

from __future__ import annotations

import httpx

POSTMARK_API_URL = "https://api.postmarkapp.com/email"


class PostmarkClient:
    def __init__(self, server_token: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._server_token = server_token
        self._client = http_client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send_email(
        self,
        from_address: str,
        to_addresses: list[str],
        subject: str,
        text_body: str,
        html_body: str,
    ) -> None:
        payload = {
            "From": from_address,
            "To": ", ".join(to_addresses),
            "Subject": subject,
            "TextBody": text_body,
            "HtmlBody": html_body,
        }
        resp = await self._client.post(
            POSTMARK_API_URL,
            headers={
                "X-Postmark-Server-Token": self._server_token,
                "Accept": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
