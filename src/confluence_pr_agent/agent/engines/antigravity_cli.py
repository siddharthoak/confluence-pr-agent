"""ChangeEngine backed by Google's Antigravity CLI (`agy`), the successor to
Gemini CLI.

Requires the `agy` binary on PATH. Unlike every other engine here,
Antigravity CLI has NO API-key auth path -- it's OAuth-only: "headless mode
uses cached credentials; authenticate once with an interactive agy session
first." A run with no cached credentials fails outright. In a container,
that means either mounting a volume with credentials from a prior
`agy login` on the host, or running one interactive login inside the
container before headless use. There is nothing this engine can do
programmatically to satisfy that -- it will just surface the CLI's own
authentication-required error as a failed ChangeAgentResult.
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

CLI_BINARY = "agy"


def parse_response(stdout: str) -> str:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip() or "(agy produced no output)"
    response = data.get("response")
    return response if isinstance(response, str) and response else (stdout.strip() or "(no response field)")


def parse_usage(stdout: str) -> dict | None:
    """Antigravity's docs confirm a "response" field in its JSON envelope but
    don't document a usage/stats field the way Gemini CLI's do (unsurprising
    -- it's young and OAuth-only, not built for the same CI/cost-tracking
    use cases). Checked defensively rather than asserted; None if absent.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    for key in ("stats", "usage"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return None


class AntigravityCliEngine:
    async def implement_change(self, repo_dir: Path, diff: PageDiff, max_turns: int) -> ChangeAgentResult:
        if shutil.which(CLI_BINARY) is None:
            return ChangeAgentResult(
                success=False,
                summary=(
                    f"'{CLI_BINARY}' (Antigravity CLI) not found on PATH. "
                    "See https://antigravity.google/docs/cli/overview to install."
                ),
            )

        prompt = build_combined_prompt(diff)
        args = [CLI_BINARY, "-p", prompt, "--dangerously-skip-permissions", "--output-format", "json"]
        timeout = turns_to_timeout_seconds(max_turns)

        try:
            returncode, stdout, stderr = await run_cli(args, cwd=repo_dir, timeout_seconds=timeout)
        except EngineTimeoutError as exc:
            return ChangeAgentResult(success=False, summary=str(exc))

        return ChangeAgentResult(
            success=returncode == 0,
            summary=parse_response(stdout),
            raw_log=f"stdout:\n{stdout}\n\nstderr:\n{stderr}",
            usage=parse_usage(stdout),
        )
