"""Declarative list of every .env field the config UI edits.

Single source of truth for both rendering the form (GET /ui/config) and
processing the submission (POST /ui/config) -- see ui/routes.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Every engine the pipeline supports, regardless of whether any have run yet
# -- the single source of truth for both the config form's dropdown and the
# /ui/runs filter dropdown (which must not be limited to engines that
# happen to already appear in run history).
ALL_ENGINES = ["claude_code", "cursor", "copilot", "codex", "gemini", "antigravity"]

# Keys whose current value is never redisplayed in the form. Submitting one
# blank means "leave it unchanged", not "clear it" -- see routes.py.
ENGINE_CREDENTIAL_KEYS = (
    "ANTHROPIC_API_KEY",
    "CURSOR_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
)

ENGINE_CREDENTIAL_BY_ENGINE = {
    "claude_code": "ANTHROPIC_API_KEY",
    "cursor": "CURSOR_API_KEY",
    "codex": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "copilot": None,  # reuses GITHUB_TOKEN
    "antigravity": None,  # OAuth-only
}


@dataclass
class ConfigField:
    key: str
    label: str
    group: str
    secret: bool = False
    input_type: str = "text"  # text | password | number | select | taglist
    options: list[str] = field(default_factory=list)
    placeholder: str = ""
    help_text: str = ""


CONFIG_FIELDS: list[ConfigField] = [
    # Confluence
    ConfigField(
        "CONFLUENCE_BASE_URL", "Confluence base URL", "Confluence",
        placeholder="https://your-team.atlassian.net/wiki",
    ),
    ConfigField("CONFLUENCE_SPACE_KEY", "Space key", "Confluence", placeholder="SD"),
    ConfigField("CONFLUENCE_USER_EMAIL", "Account email", "Confluence", placeholder="you@example.com"),
    ConfigField("CONFLUENCE_API_TOKEN", "API token", "Confluence", secret=True),
    ConfigField(
        "CONFLUENCE_WEBHOOK_SECRET", "Webhook secret (optional)", "Confluence", secret=True,
        help_text="Leave blank to disable signature verification on inbound webhooks.",
    ),
    ConfigField(
        "CONFLUENCE_ALLOWED_LABELS", "Allowed page labels", "Confluence", input_type="taglist",
        help_text=(
            "Only pages carrying at least one of these Confluence labels are processed -- "
            "everything else (meeting notes, design docs, other project content) is ignored. "
            "Leave empty to process any page (no filtering)."
        ),
    ),
    # GitHub / target repo
    ConfigField("TARGET_REPO", "Target repo", "GitHub", placeholder="owner/name"),
    ConfigField("TARGET_REPO_BASE_BRANCH", "Base branch", "GitHub", placeholder="main"),
    ConfigField("TARGET_REPO_TEST_COMMAND", "Test command", "GitHub", placeholder="pytest"),
    ConfigField("GITHUB_TOKEN", "GitHub PAT", "GitHub", secret=True),
    # Change engine
    ConfigField(
        "CHANGE_AGENT_ENGINE", "Change engine", "Change engine", input_type="select",
        options=ALL_ENGINES,
    ),
    ConfigField(
        "CHANGE_AGENT_MAX_TURNS", "Max turns / timeout budget", "Change engine", input_type="number",
        placeholder="30",
    ),
    ConfigField(
        "ANTHROPIC_API_KEY", "Anthropic API key (claude_code)", "Change engine", secret=True,
        help_text="Also used by the LLM Judge review gate below when its provider is set to Anthropic.",
    ),
    ConfigField("CURSOR_API_KEY", "Cursor API key (cursor)", "Change engine", secret=True),
    ConfigField(
        "OPENAI_API_KEY", "OpenAI API key (codex)", "Change engine", secret=True,
        help_text="Also used by the LLM Judge review gate below when its provider is set to OpenAI.",
    ),
    ConfigField("GEMINI_API_KEY", "Gemini API key (gemini)", "Change engine", secret=True),
    # LLM judge
    ConfigField(
        "JUDGE_ENABLED", "LLM Judge review gate", "LLM Judge", input_type="select", options=["true", "false"],
        help_text=(
            "After tests pass, an independent LLM call reviews the actual code diff against the "
            "Confluence spec change and can still reject it before a PR opens -- catches diffs that pass "
            "tests without correctly implementing the spec, or that touch unrelated files. Independent of "
            "the change engine above by design, so it isn't the same model grading its own work. If the "
            "selected provider's API key isn't set (or the call fails), this step is skipped rather than "
            "blocking the PR."
        ),
    ),
    ConfigField(
        "JUDGE_PROVIDER", "LLM Judge provider", "LLM Judge", input_type="select", options=["anthropic", "openai"],
        help_text="Uses the matching API key above (Anthropic or OpenAI) -- not tied to CHANGE_AGENT_ENGINE.",
    ),
    ConfigField(
        "JUDGE_MODEL", "LLM Judge model", "LLM Judge",
        placeholder="blank = provider default (claude-sonnet-5 / gpt-4.1)",
    ),
    # Email
    ConfigField("SENDGRID_API_KEY", "SendGrid API key", "Email", secret=True),
    ConfigField("EMAIL_FROM_ADDRESS", "From address", "Email", placeholder="confluence-pr-agent@example.com"),
    ConfigField("EMAIL_TO_ADDRESSES", "To addresses", "Email", help_text="Comma-separated."),
]

CONFIG_FIELDS_BY_KEY = {f.key: f for f in CONFIG_FIELDS}
