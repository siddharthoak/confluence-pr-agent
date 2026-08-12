"""The pipeline's stage sequence -- shared between the orchestrator (which
marks progress through it in RunRecord.current_stage as it goes) and the UI
(which turns that into a stepper diagram, live during a "running" run and
retrospectively afterward). One source of truth so the two can't drift.
"""

from __future__ import annotations

STAGE_KEYS = [
    "fetch_page", "create_jira_story", "clone_repo", "ai_agent", "run_tests", "llm_judge", "open_pr", "send_email",
]

STAGE_LABELS = {
    "fetch_page": "Confluence",
    "create_jira_story": "Jira Story",
    "clone_repo": "Clone Repo",
    "ai_agent": "AI Agent",
    "run_tests": "Tests",
    "llm_judge": "LLM Judge",
    "open_pr": "Pull Request",
    "send_email": "Email",
}
