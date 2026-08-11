"""SendGrid HTTP API client for the post-PR team notification email."""

from __future__ import annotations

import httpx

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class SendGridClient:
    def __init__(self, api_key: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
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
            "personalizations": [{"to": [{"email": addr} for addr in to_addresses]}],
            "from": {"email": from_address},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html", "value": html_body},
            ],
        }
        resp = await self._client.post(
            SENDGRID_API_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
        )
        resp.raise_for_status()
