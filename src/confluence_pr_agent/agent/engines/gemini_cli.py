"""ChangeEngine backed by Google's Gemini CLI (`gemini`).

Requires the `gemini` binary on PATH (npm install -g @google/gemini-cli,
Node 18+) and GEMINI_API_KEY. Gemini CLI does have a native turn-limit
concept (maxSessionTurns), but it's a settings.json value, not a CLI flag --
rather than mutate the user's Gemini config file, max_turns is converted
into a wall-clock timeout instead, same as the other CLI-based engines.

--skip-trust is required: Gemini CLI refuses to run tools in a directory it
hasn't been told to trust, even with --yolo, and a freshly-cloned repo is
never pre-trusted. Confirmed live -- without it, every run fails immediately
with "Gemini CLI is not running in a trusted directory" on stderr (which
--yolo alone does not silence or bypass).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from confluence_pr_agent.agent.engines._subprocess_utils import (
    EngineTimeoutError,
    run_cli,
    turns_to_timeout_seconds,
)
from confluence_pr_agent.agent.prompts import build_combined_prompt
from confluence_pr_agent.models import ChangeAgentResult, PageDiff

CLI_BINARY = "gemini"


def parse_response(stdout: str) -> str:
    """Gemini's --output-format json prints a single JSON object with a "response" field."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip() or "(gemini produced no output)"
    response = data.get("response")
    return response if isinstance(response, str) and response else (stdout.strip() or "(no response field)")


def parse_usage(stdout: str) -> dict | None:
    """Gemini's JSON envelope includes a "stats" object (token usage/latency);
    passed through as-is since its exact shape isn't part of any stable
    contract worth hardcoding field names against.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    stats = data.get("stats")
    return stats if isinstance(stats, dict) else None


class GeminiCliEngine:
    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def implement_change(
        self, repo_dir: Path, diff: PageDiff, max_turns: int, retry_context: str | None = None
    ) -> ChangeAgentResult:
        if shutil.which(CLI_BINARY) is None:
            return ChangeAgentResult(
                success=False,
                summary=f"'{CLI_BINARY}' (Gemini CLI) not found on PATH. Install: npm install -g @google/gemini-cli",
            )

        prompt = build_combined_prompt(diff, retry_context)
        args = [CLI_BINARY, "-p", prompt, "--yolo", "--skip-trust", "--output-format", "json"]
        timeout = turns_to_timeout_seconds(max_turns)
        extra_env = {"GEMINI_API_KEY": self._api_key} if self._api_key else None

        try:
            returncode, stdout, stderr = await run_cli(
                args, cwd=repo_dir, timeout_seconds=timeout, extra_env=extra_env
            )
        except EngineTimeoutError as exc:
            return ChangeAgentResult(success=False, summary=str(exc))

        return ChangeAgentResult(
            success=returncode == 0,
            summary=parse_response(stdout),
            raw_log=f"stdout:\n{stdout}\n\nstderr:\n{stderr}",
            usage=parse_usage(stdout),
        )
