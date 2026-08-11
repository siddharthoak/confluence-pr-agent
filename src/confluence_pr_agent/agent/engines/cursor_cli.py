"""ChangeEngine backed by the Cursor CLI (`agent`).

Requires the `agent` binary on PATH (install: curl https://cursor.com/install
-fsS | bash) and CURSOR_API_KEY set in the environment. Cursor's CLI has no
native "max turns" concept, so max_turns is translated into a wall-clock
timeout instead (see _subprocess_utils.turns_to_timeout_seconds).
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

CLI_BINARY = "agent"


def parse_result(stdout: str) -> str:
    """Cursor's --output-format json prints one JSON object with a "result" field."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip() or "(cursor agent produced no output)"
    result = data.get("result")
    return result if isinstance(result, str) and result else (stdout.strip() or "(no result field)")


def parse_usage(stdout: str) -> dict | None:
    """Checked defensively for a usage/stats/cost sub-object -- Cursor's docs
    confirm structured JSON output but don't pin down a stable field name
    for token/cost usage, so nothing is asserted about its shape.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    for key in ("usage", "stats", "cost"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return None


class CursorCliEngine:
    async def implement_change(self, repo_dir: Path, diff: PageDiff, max_turns: int) -> ChangeAgentResult:
        if shutil.which(CLI_BINARY) is None:
            return ChangeAgentResult(
                success=False,
                summary=(
                    f"'{CLI_BINARY}' (Cursor CLI) not found on PATH. "
                    "Install: curl https://cursor.com/install -fsS | bash"
                ),
            )

        prompt = build_combined_prompt(diff)
        args = [CLI_BINARY, "-p", "--force", "--output-format", "json", prompt]
        timeout = turns_to_timeout_seconds(max_turns)

        try:
            returncode, stdout, stderr = await run_cli(args, cwd=repo_dir, timeout_seconds=timeout)
        except EngineTimeoutError as exc:
            return ChangeAgentResult(success=False, summary=str(exc))

        return ChangeAgentResult(
            success=returncode == 0,
            summary=parse_result(stdout),
            raw_log=f"stdout:\n{stdout}\n\nstderr:\n{stderr}",
            usage=parse_usage(stdout),
        )
