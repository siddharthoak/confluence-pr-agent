"""Browser UI: configure credentials, browse run history, simulate a webhook.

All three pages are unauthenticated -- fine for a POC bound to 127.0.0.1
(see podman-compose.yml), NOT something to expose beyond a trusted network
without adding auth first, since /ui/config both reads and writes secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from confluence_pr_agent.config import get_settings
from confluence_pr_agent.pipeline.stages import STAGE_LABELS
from confluence_pr_agent.storage.run_store import RunStore
from confluence_pr_agent.ui.config_fields import ALL_ENGINES, CONFIG_FIELDS, ENGINE_CREDENTIAL_BY_ENGINE
from confluence_pr_agent.ui.diff_view import render_diff_html
from confluence_pr_agent.ui.pipeline_flow import build_flow_steps
from confluence_pr_agent.ui.usage_summary import summarize_usage

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Every status run_pipeline can record -- see models.py::PipelineResult.status
# and orchestrator.py's "running" placeholder. Fixed, not derived from run
# history, for the same reason as ALL_ENGINES: the filter shouldn't be
# limited to outcomes that happen to have occurred yet.
ALL_STATUSES = [
    "running", "opened_pr", "tests_failed", "judge_rejected", "error", "no_change_detected", "ignored",
]

STATUS_LABELS = {
    "running": "Running",
    "opened_pr": "Open PR",
    "tests_failed": "Tests Failed",
    "judge_rejected": "Judge Rejected",
    "error": "Error",
    "no_change_detected": "No Change",
    "ignored": "Ignored (label)",
}


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


# Registered as a Jinja filter (`{{ run.status | status_label }}`) so every
# template that shows a status -- the filter dropdown, table badges, the
# detail page header -- uses the same human-readable text without each one
# needing the mapping threaded into its own route's context.
templates.env.filters["status_label"] = _status_label
templates.env.filters["stage_label"] = lambda stage: STAGE_LABELS.get(stage, stage)

ENV_PATH = Path(".env")


def _write_env_updates(path: Path, updates: dict[str, str]) -> None:
    # Deliberately not python-dotenv's set_key(): it writes via a temp file
    # + os.replace() rename, which raises "Device or resource busy" when
    # .env is bind-mounted as a single file into the container (the rename
    # target is a mount point, not a plain file the kernel will let us
    # replace). Rewriting the existing file's content in place sidesteps
    # that entirely.
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(updates)
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)
    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")
    path.write_text("\n".join(new_lines) + "\n")


@router.get("/ui")
async def ui_home() -> RedirectResponse:
    return RedirectResponse(url="/ui/runs")


# ---------------------------------------------------------------------------
# How it works -- a walkthrough of the pipeline for live demos, so the
# journey can be narrated step by step inside the app itself instead of a
# separate slide deck. Built from a synthetic, fully-"done" run through
# build_flow_steps() so the overview diagram at the top always matches
# pipeline/stages.py -- the same source of truth /ui/runs/{id} uses -- and
# can't quietly drift out of sync with the real pipeline.
# ---------------------------------------------------------------------------


@router.get("/ui/how-it-works")
async def how_it_works(request: Request):
    settings = get_settings()
    demo_run = {
        "status": "opened_pr",
        "current_stage": "send_email",
        "engine": settings.change_agent_engine,
        "target_repo": settings.target_repo,
        "page_id": "458753",
        "page_title": "Checkout Flow Spec",
        "files_changed": ["src/checkout.py", "tests/test_checkout.py"],
        "pr_number": 42,
        "email_sent": True,
        "email_error": None,
        "judge_verdict": "approved",
    }
    return templates.TemplateResponse(
        request,
        "how_it_works.html",
        {
            "flow_steps": build_flow_steps(demo_run),
            "settings": settings,
        },
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _current_env_values() -> dict[str, str]:
    # Reads os.environ, not the .env file: when this container was started
    # with `--env-file .env` (rather than a bind-mounted .env), the values
    # only ever exist as real process env vars -- no file to read is
    # actually present inside the container. os.environ is also what
    # config.get_settings() itself resolves from (config.py's
    # load_dotenv(override=True) already folded any .env file into it at
    # startup), so this is the one accurate source regardless of how the
    # service was launched.
    return {f.key: os.environ.get(f.key, "") for f in CONFIG_FIELDS}


def _config_context(saved: bool = False, error: str | None = None) -> dict:
    values = _current_env_values()
    groups: dict[str, list[dict]] = {}
    for f in CONFIG_FIELDS:
        current = values.get(f.key, "")
        groups.setdefault(f.group, []).append(
            {
                "field": f,
                "display_value": "" if f.secret else current,
                "is_set": bool(current),
            }
        )
    return {
        "groups": groups,
        "saved": saved,
        "error": error,
        "engine_credential_by_engine": ENGINE_CREDENTIAL_BY_ENGINE,
    }


@router.get("/ui/config")
async def config_form(request: Request):
    return templates.TemplateResponse(request, "config.html", _config_context())


@router.post("/ui/config")
async def save_config(request: Request):
    form = await request.form()

    # Written to both places deliberately: os.environ so the change is live
    # for this process immediately (this is what get_settings() and every
    # engine subprocess actually reads), and the .env file so it survives a
    # container restart -- but only if that file is writable from in here,
    # which requires it to be bind-mounted rather than passed via
    # `--env-file` at container creation (env-file only sets process env,
    # it doesn't put a file on the container's filesystem). See SETUP.md.
    if not ENV_PATH.exists():
        ENV_PATH.write_text("")

    updates: dict[str, str] = {}
    for f in CONFIG_FIELDS:
        raw = form.get(f.key)
        if raw is None:
            continue
        value = str(raw).strip()
        if f.secret and value == "":
            continue  # blank secret field means "leave unchanged" -- we never redisplay it
        os.environ[f.key] = value
        updates[f.key] = value

    if updates:
        _write_env_updates(ENV_PATH, updates)

    get_settings.cache_clear()
    return RedirectResponse(url="/ui/config?saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def _filter_runs(runs: list[dict], *, engine: str, status: str, date_from: str, date_to: str) -> list[dict]:
    filtered = runs
    if engine:
        filtered = [r for r in filtered if r.get("engine") == engine]
    if status:
        filtered = [r for r in filtered if r.get("status") == status]
    if date_from:
        # started_at is a full ISO timestamp; date_from/date_to are bare
        # "YYYY-MM-DD" values from an <input type="date">. Comparing the
        # date prefix as a string works because ISO dates sort lexically.
        filtered = [r for r in filtered if r.get("started_at", "")[:10] >= date_from]
    if date_to:
        filtered = [r for r in filtered if r.get("started_at", "")[:10] <= date_to]
    return filtered


@router.get("/ui/runs")
async def runs_list(
    request: Request, engine: str = "", status: str = "", date_from: str = "", date_to: str = ""
):
    settings = get_settings()
    store = RunStore(settings.runs_store_path)
    all_runs = store.list_runs()

    runs = _filter_runs(all_runs, engine=engine, status=status, date_from=date_from, date_to=date_to)

    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "runs": runs,
            "total_count": len(all_runs),
            "filters": {"engine": engine, "status": status, "date_from": date_from, "date_to": date_to},
            "engines_available": ALL_ENGINES,
            "statuses_available": ALL_STATUSES,
            "any_filter_active": bool(engine or status or date_from or date_to),
        },
    )


@router.post("/ui/runs/delete-all")
async def delete_all_runs():
    settings = get_settings()
    RunStore(settings.runs_store_path).clear_all()
    return RedirectResponse(url="/ui/runs", status_code=303)


@router.post("/ui/runs/{run_id}/delete")
async def delete_run(run_id: str):
    settings = get_settings()
    RunStore(settings.runs_store_path).delete_run(run_id)
    return RedirectResponse(url="/ui/runs", status_code=303)


@router.get("/ui/runs/{run_id}")
async def run_detail(request: Request, run_id: str):
    settings = get_settings()
    store = RunStore(settings.runs_store_path)
    run = store.get_run(run_id)
    if run is None:
        return templates.TemplateResponse(
            request, "run_detail.html", {"run": None, "run_id": run_id}, status_code=404
        )
    spec_diff = run.get("spec_diff")
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "run": run,
            "run_id": run_id,
            "usage_summary": summarize_usage(run.get("usage")),
            "flow_steps": build_flow_steps(run),
            "spec_diff_html": render_diff_html(spec_diff) if spec_diff else None,
        },
    )


# ---------------------------------------------------------------------------
# Webhook simulator
# ---------------------------------------------------------------------------


def _build_webhook_payload(page_id: str, title: str, space_key: str) -> dict:
    page: dict[str, str] = {"id": page_id}
    if title:
        page["title"] = title
    if space_key:
        page["spaceKey"] = space_key
    return {"event": "page_updated", "page": page, "timestamp": int(time.time() * 1000)}


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _post_webhook(url: str, body: bytes, headers: dict[str, str]) -> httpx.Response:
    """A real, socket-based HTTP call -- deliberately not httpx.ASGITransport.

    ASGITransport dispatches in-process with no real socket to detach from,
    so Starlette's BackgroundTasks (attached to the /webhook/confluence
    response) run to completion *before* this call returns -- meaning the
    /ui/simulate request would block for the entire pipeline run (confirmed:
    minutes, for a real agentic engine) instead of returning immediately
    like a real webhook delivery does. A genuine socket round-trip doesn't
    have that problem: the response is flushed once the route handler
    returns, and the background task keeps running server-side after that,
    same as a real Confluence-to-us webhook call.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await client.post(url, content=body, headers=headers)


@router.get("/ui/simulate")
async def simulate_form(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "simulate.html",
        {
            "default_space_key": settings.confluence_space_key,
            "prefill": None,
            "result": None,
            "error": None,
        },
    )


@router.post("/ui/simulate")
async def simulate_submit(request: Request):
    form = await request.form()
    settings = get_settings()

    page_id = str(form.get("page_id") or "").strip()
    title = str(form.get("title") or "").strip()
    space_key = str(form.get("space_key") or "").strip()
    prefill = {"page_id": page_id, "title": title, "space_key": space_key}

    if not page_id or not page_id.isdigit():
        return templates.TemplateResponse(
            request,
            "simulate.html",
            {
                "default_space_key": settings.confluence_space_key,
                "prefill": prefill,
                "result": None,
                "error": "Page ID is required and must be numeric -- it's the number in the page's Confluence URL.",
            },
            status_code=400,
        )

    payload = _build_webhook_payload(page_id, title, space_key or settings.confluence_space_key)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings.confluence_webhook_secret:
        headers["X-Hub-Signature-256"] = _sign(settings.confluence_webhook_secret, body)

    # Derived from the incoming request rather than settings.webhook_port --
    # guaranteed to match whatever host:port this server is actually bound
    # to (the container always exposes 8000; a bare local `uvicorn --port X`
    # run could differ from the .env default).
    webhook_url = str(request.base_url).rstrip("/") + "/webhook/confluence"
    try:
        resp = await _post_webhook(webhook_url, body, headers)
        result = {"ok": resp.status_code == 200, "status_code": resp.status_code, "body": resp.text}
    except httpx.HTTPError as exc:
        result = {"ok": False, "status_code": None, "body": str(exc)}

    return templates.TemplateResponse(
        request,
        "simulate.html",
        {
            "default_space_key": settings.confluence_space_key,
            "prefill": prefill,
            "result": result,
            "payload_sent": json.dumps(payload, indent=2),
            "error": None,
        },
    )
