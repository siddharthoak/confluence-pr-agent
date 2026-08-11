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
def settings(tmp_path: Path) -> Settings:
    return Settings(
        confluence_base_url="https://neurealm-team-juadifpx.atlassian.net/wiki",
        confluence_space_key="SD",
        confluence_user_email="test@example.com",
        confluence_api_token="test-token",
        github_token="test-gh-token",
        target_repo="acme/widgets",
        target_repo_base_branch="main",
        target_repo_test_command="pytest",
        anthropic_api_key="test-anthropic-key",
        sendgrid_api_key="test-sendgrid-key",
        email_from_address="agent@example.com",
        email_to_addresses="team@example.com,lead@example.com",
        data_dir=str(tmp_path / "data"),
    )
