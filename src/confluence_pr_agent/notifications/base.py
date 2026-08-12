"""The interface every email provider implements -- mirrors agent/base.py's
ChangeEngine and judge/base.py's ChangeJudge, now that there are two
(SendGrid, Postmark) rather than one hardcoded client.
"""

from __future__ import annotations

from typing import Protocol


class EmailClient(Protocol):
    async def send_email(
        self,
        from_address: str,
        to_addresses: list[str],
        subject: str,
        text_body: str,
        html_body: str,
    ) -> None: ...

    async def aclose(self) -> None: ...
