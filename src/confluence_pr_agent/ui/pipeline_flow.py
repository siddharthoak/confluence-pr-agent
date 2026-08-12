"""Turns a run record into a stepper diagram: the same component serves as
a live progress indicator while a run's status is "running" and as a
retrospective "how was this built" summary once it's finished -- both are
just different snapshots of the same pipeline/stages.py sequence.
"""

from __future__ import annotations

from confluence_pr_agent.pipeline.stages import STAGE_KEYS, STAGE_LABELS


def _detail_for(key: str, run: dict) -> str | None:
    if key == "fetch_page":
        return run.get("page_title") or run.get("page_id") or None
    if key == "clone_repo":
        return run.get("target_repo") or None
    if key == "ai_agent":
        engine = run.get("engine") or ""
        n = len(run.get("files_changed") or [])
        if n:
            return f"{engine} · {n} file{'s' if n != 1 else ''} changed"
        return engine or None
    if key == "run_tests":
        return None  # pass/fail communicated by the step's color state, not text
    if key == "llm_judge":
        verdict = run.get("judge_verdict")
        return verdict.capitalize() if verdict else None
    if key == "open_pr":
        return f"#{run['pr_number']}" if run.get("pr_number") else None
    if key == "send_email":
        if run.get("email_sent"):
            return "sent"
        if run.get("email_error"):
            return "not sent"
        return None
    return None


def build_flow_steps(run: dict) -> list[dict]:
    status = run.get("status")
    current_stage = run.get("current_stage") or STAGE_KEYS[0]
    current_index = STAGE_KEYS.index(current_stage) if current_stage in STAGE_KEYS else 0

    steps = []
    for i, key in enumerate(STAGE_KEYS):
        if status == "running":
            state = "done" if i < current_index else "active" if i == current_index else "pending"
        elif status in ("error", "tests_failed", "judge_rejected"):
            state = "done" if i < current_index else "failed" if i == current_index else "skipped"
        elif status in ("no_change_detected", "ignored"):
            state = "done" if i <= current_index else "skipped"
        elif status == "opened_pr":
            if key == "llm_judge":
                state = "done" if run.get("judge_verdict") else "skipped"
            elif key == "send_email":
                state = "done" if run.get("email_sent") else "skipped"
            else:
                state = "done"
        else:
            state = "pending"
        steps.append({"key": key, "label": STAGE_LABELS[key], "detail": _detail_for(key, run), "state": state})
    return steps
