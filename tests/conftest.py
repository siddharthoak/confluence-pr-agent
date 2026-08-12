from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from confluence_pr_agent.config import Settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture() -> Callable[[str], dict]:
    def _load(name: str) -> dict:
        return json.loads((FIXTURES_DIR / name).read_text())

    return _load


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    # Full isolation from whatever the real developer .env happens to
    # contain -- config.py's load_dotenv(override=True) folds it into
    # os.environ at import time, and pydantic-settings *also* reads .env
    # directly as its own source (env_file=".env" in config.py's
    # SettingsConfigDict), independent of os.environ. Any field not passed
    # explicitly below would otherwise silently take whatever's in the real
    # .env instead of Settings' own hardcoded default -- hit twice already
    # in one session (CONFLUENCE_ALLOWED_LABELS, then JUDGE_ENABLED /
    # JIRA_SUGGEST_STORY_POINTS toggled for real usage broke assumptions
    # several unrelated tests were relying on). Clearing every field's env
    # var closes the os.environ half; `_env_file=None` closes the
    # direct-file-read half.
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)

    return Settings(
        _env_file=None,
        confluence_base_url="https://neurealm-team-juadifpx.atlassian.net/wiki",
        confluence_space_key="SD",
        confluence_user_email="test@example.com",
        confluence_api_token="test-token",
        github_token="test-gh-token",
        target_repo="acme/widgets",
        target_repo_base_branch="main",
        target_repo_test_command="pytest",
        anthropic_api_key="test-anthropic-key",
        email_provider="sendgrid",
        sendgrid_api_key="test-sendgrid-key",
        email_from_address="agent@example.com",
        email_to_addresses="team@example.com,lead@example.com",
        data_dir=str(tmp_path / "data"),
    )
