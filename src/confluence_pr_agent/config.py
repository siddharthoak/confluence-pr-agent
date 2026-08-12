"""Central configuration, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Populate the real process environment too (not just this module's Settings
# object) -- every change engine shells out to its own CLI subprocess, which
# reads its API key (ANTHROPIC_API_KEY / CURSOR_API_KEY / GITHUB_TOKEN)
# straight from os.environ, not from this Settings object.
#
# override=True is deliberate: .env (and the /ui/config form that writes to
# it) is meant to be the authoritative source of truth for this service.
# Without it, a stale environment variable from the parent shell would
# silently win over a value someone just saved in the UI -- pydantic-settings
# has the same real-env-wins-over-.env-file default, so this also covers it,
# since Settings() reads os.environ *after* this line has already run.
load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Confluence
    confluence_base_url: str = Field(default="https://example.atlassian.net/wiki")
    confluence_space_key: str = Field(default="SD")
    confluence_user_email: str = Field(default="")
    confluence_api_token: str = Field(default="")
    confluence_webhook_secret: str = Field(default="")
    # Comma-separated Confluence labels. A page must have at least one of
    # these to be processed -- e.g. "brd,spec-for-agent" so other project
    # content (meeting notes, design docs) in the same space is ignored.
    # Empty = no filtering (every page is eligible), for backward compat.
    confluence_allowed_labels: str = Field(default="")

    # GitHub / target repo
    github_token: str = Field(default="")
    target_repo: str = Field(default="your-org/your-repo")
    target_repo_base_branch: str = Field(default="main")
    target_repo_test_command: str = Field(default="pytest")

    # Change engine (code-writing backend) -- one of:
    # claude_code | cursor | copilot | codex | gemini | antigravity
    change_agent_engine: str = Field(default="claude_code")
    change_agent_max_turns: int = Field(default=30)
    anthropic_api_key: str = Field(default="")  # claude_code engine + llm judge (see below)
    cursor_api_key: str = Field(default="")  # cursor engine
    openai_api_key: str = Field(default="")  # codex engine
    gemini_api_key: str = Field(default="")  # gemini engine
    # copilot engine reuses github_token below; antigravity is OAuth-only (no key)

    # LLM-as-judge review gate: after tests pass but before a PR is opened,
    # an independent LLM call reviews the actual code diff against the spec
    # change and can still reject it -- a green test suite doesn't prove the
    # spec was implemented (or implemented without scope creep). Independent
    # of CHANGE_AGENT_ENGINE by design -- see judge/factory.py. If the
    # selected provider's API key isn't set, this step is skipped rather
    # than blocking the PR (judge/factory.py::judge_configured).
    judge_enabled: bool = Field(default=True)
    judge_provider: str = Field(default="anthropic")  # anthropic | openai
    judge_model: str = Field(default="")  # blank = provider's own default (see judge/providers/*)

    # SendGrid
    sendgrid_api_key: str = Field(default="")
    email_from_address: str = Field(default="confluence-pr-agent@example.com")
    email_to_addresses: str = Field(default="team@example.com")

    # Service
    data_dir: str = Field(default="./data")
    webhook_host: str = Field(default="0.0.0.0")
    webhook_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    @property
    def email_to_list(self) -> list[str]:
        return [addr.strip() for addr in self.email_to_addresses.split(",") if addr.strip()]

    @property
    def confluence_allowed_labels_list(self) -> list[str]:
        return [label.strip().lower() for label in self.confluence_allowed_labels.split(",") if label.strip()]

    @property
    def data_dir_path(self) -> Path:
        path = Path(self.data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def workdirs_path(self) -> Path:
        path = self.data_dir_path / "workdirs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def page_store_path(self) -> Path:
        return self.data_dir_path / "page_store.json"

    @property
    def runs_store_path(self) -> Path:
        return self.data_dir_path / "runs.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
