from __future__ import annotations

from confluence_pr_agent.pipeline.stages import STAGE_KEYS
from confluence_pr_agent.ui.pipeline_flow import build_flow_steps


def _run(**overrides) -> dict:
    base = {
        "status": "running",
        "current_stage": "fetch_page",
        "engine": "gemini",
        "target_repo": "acme/widgets",
        "page_id": "1",
        "page_title": "Spec",
        "files_changed": [],
        "pr_number": None,
        "email_sent": False,
        "email_error": None,
    }
    base.update(overrides)
    return base


def test_running_marks_reached_stages_done_current_active_rest_pending():
    steps = build_flow_steps(_run(status="running", current_stage="ai_agent"))
    states = {s["key"]: s["state"] for s in steps}

    assert states["fetch_page"] == "done"
    assert states["clone_repo"] == "done"
    assert states["ai_agent"] == "active"
    assert states["run_tests"] == "pending"
    assert states["open_pr"] == "pending"
    assert states["send_email"] == "pending"


def test_no_change_detected_marks_only_fetch_page_done_rest_skipped():
    steps = build_flow_steps(_run(status="no_change_detected", current_stage="fetch_page"))
    states = {s["key"]: s["state"] for s in steps}

    assert states["fetch_page"] == "done"
    for key in STAGE_KEYS[1:]:
        assert states[key] == "skipped"


def test_error_at_ai_agent_marks_earlier_stages_done_that_stage_failed_rest_skipped():
    steps = build_flow_steps(_run(status="error", current_stage="ai_agent"))
    states = {s["key"]: s["state"] for s in steps}

    assert states["fetch_page"] == "done"
    assert states["clone_repo"] == "done"
    assert states["ai_agent"] == "failed"
    assert states["run_tests"] == "skipped"
    assert states["open_pr"] == "skipped"
    assert states["send_email"] == "skipped"


def test_tests_failed_marks_run_tests_failed_and_later_stages_skipped():
    steps = build_flow_steps(_run(status="tests_failed", current_stage="run_tests"))
    states = {s["key"]: s["state"] for s in steps}

    assert states["ai_agent"] == "done"
    assert states["run_tests"] == "failed"
    assert states["open_pr"] == "skipped"
    assert states["send_email"] == "skipped"


def test_opened_pr_marks_everything_done_including_email_when_sent():
    steps = build_flow_steps(_run(status="opened_pr", current_stage="send_email", email_sent=True, pr_number=7))
    states = {s["key"]: s["state"] for s in steps}

    for key in STAGE_KEYS:
        assert states[key] == "done"


def test_opened_pr_marks_email_skipped_when_not_sent():
    steps = build_flow_steps(
        _run(status="opened_pr", current_stage="send_email", email_sent=False, email_error="not configured")
    )
    states = {s["key"]: s["state"] for s in steps}

    assert states["open_pr"] == "done"
    assert states["send_email"] == "skipped"


def test_details_reflect_engine_files_and_pr_number():
    steps = build_flow_steps(
        _run(
            status="opened_pr",
            current_stage="send_email",
            engine="codex",
            files_changed=["a.py", "b.py"],
            pr_number=3,
            email_sent=True,
        )
    )
    by_key = {s["key"]: s for s in steps}

    assert "codex" in by_key["ai_agent"]["detail"]
    assert "2 files" in by_key["ai_agent"]["detail"]
    assert by_key["open_pr"]["detail"] == "#3"
    assert by_key["send_email"]["detail"] == "sent"
