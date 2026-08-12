"""ChangeEngine backed by the GitHub Copilot CLI (`copilot`).

Requires the `copilot` binary on PATH (npm install -g @github/copilot, Node
22+) and a token in GH_TOKEN / GITHUB_TOKEN / COPILOT_GITHUB_TOKEN -- we
already load GITHUB_TOKEN from .env, so no extra credential is needed.
Like Cursor's CLI, there's no native "max turns" concept, so max_turns is
translated into a wall-clock timeout.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from confluence_pr_agent.agent.engines._subprocess_utils import (
    EngineTimeoutError,
    run_cli,
    turns_to_timeout_seconds,
)
from confluence_pr_agent.agent.prompts import build_combined_prompt
from confluence_pr_agent.models import ChangeAgentResult, PageDiff

CLI_BINARY = "copilot"


class CopilotCliEngine:
    async def implement_change(
        self, repo_dir: Path, diff: PageDiff, max_turns: int, retry_context: str | None = None
    ) -> ChangeAgentResult:
        if shutil.which(CLI_BINARY) is None:
            return ChangeAgentResult(
                success=False,
                summary=f"'{CLI_BINARY}' (GitHub Copilot CLI) not found on PATH. Install: npm install -g @github/copilot",
            )

        prompt = build_combined_prompt(diff, retry_context)
        args = [CLI_BINARY, "-p", prompt, "--allow-all-tools", "--no-ask-user", "-s"]
        timeout = turns_to_timeout_seconds(max_turns)

        try:
            returncode, stdout, stderr = await run_cli(args, cwd=repo_dir, timeout_seconds=timeout)
        except EngineTimeoutError as exc:
            return ChangeAgentResult(success=False, summary=str(exc))

        summary = stdout.strip() or "(copilot produced no output)"
        return ChangeAgentResult(
            success=returncode == 0,
            summary=summary,
            raw_log=f"stdout:\n{stdout}\n\nstderr:\n{stderr}",
        )
