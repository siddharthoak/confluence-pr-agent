"""FastAPI webhook receiver for Confluence "page updated" events."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from confluence_pr_agent.config import get_settings
from confluence_pr_agent.pipeline.orchestrator import run_pipeline
from confluence_pr_agent.pipeline.poller import poll_loop
from confluence_pr_agent.ui.routes import router as ui_router
from confluence_pr_agent.webhook.schemas import extract_event_type, extract_page_id

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    poll_task: asyncio.Task | None = None
    if settings.confluence_poll_enabled:
        logger.info("Starting Confluence poll loop (every %ss)", settings.confluence_poll_interval_seconds)
        poll_task = asyncio.create_task(poll_loop(settings))
    yield
    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Confluence-to-PR Change Agent",
    description="Receives Confluence page-updated webhooks and drives the spec-to-PR pipeline.",
    lifespan=lifespan,
)
app.include_router(ui_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify an HMAC-SHA256 signature if a shared secret is configured.

    Verification is skipped (returns True) when no secret is configured --
    fine for local POC use, not recommended for a publicly reachable endpoint.
    """
    if not secret:
        return True
    if not signature_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


@app.post("/webhook/confluence")
async def confluence_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()
    raw_body = await request.body()

    if not _verify_signature(settings.confluence_webhook_secret, raw_body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    payload = await request.json()
    page_id = extract_page_id(payload)
    event_type = extract_event_type(payload)

    if page_id is None:
        raise HTTPException(status_code=400, detail="could not find a page id in the webhook payload")

    logger.info("Received Confluence webhook event=%s page_id=%s", event_type, page_id)
    background_tasks.add_task(run_pipeline, page_id)

    return {"status": "accepted", "page_id": page_id}


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.webhook_host, port=settings.webhook_port)
