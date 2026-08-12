"""ChangeEngine backed by the OpenAI Codex CLI (`codex exec`).

Requires the `codex` binary on PATH (npm install -g @openai/codex, Node 22+)
and an API key. `codex exec` must run inside a git repo (true for our
cloned target repo) and has no cwd flag -- we set the subprocess cwd
instead, same as the other CLI engines. Like cursor/copilot, there's no
native "max turns" concept, so max_turns becomes a wall-clock timeout.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from confluence_pr_agent.agent.engines._subprocess_utils import (
    EngineTimeoutError,
    run_cli,
    turns_to_timeout_seconds,
)
from confluence_pr_agent.agent.prompts import build_combined_prompt
from confluence_pr_agent.models import ChangeAgentResult, PageDiff

CLI_BINARY = "codex"


def parse_usage(stdout: str) -> dict | None:
    """codex exec --json emits JSON Lines (one event per line, not a single
    blob) -- turn.completed/item.completed events carry a "usage" (token
    counts) field per OpenAI's own docs. Scans for the last one, since it's
    the most complete/cumulative figure for the run.
    """
    usage: dict | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidate = event.get("usage")
        if isinstance(candidate, dict):
            usage = candidate
    return usage


class CodexCliEngine:
    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def implement_change(
        self, repo_dir: Path, diff: PageDiff, max_turns: int, retry_context: str | None = None
    ) -> ChangeAgentResult:
        if shutil.which(CLI_BINARY) is None:
            return ChangeAgentResult(
                success=False,
                summary=f"'{CLI_BINARY}' (OpenAI Codex CLI) not found on PATH. Install: npm install -g @openai/codex",
            )

        prompt = build_combined_prompt(diff, retry_context)
        timeout = turns_to_timeout_seconds(max_turns)

        # -o writes just the final response text to a file, sparing us from
        # having to parse the --json event stream to find it.
        with tempfile.NamedTemporaryFile(mode="r", suffix=".txt", delete=False) as tmp:
            result_path = Path(tmp.name)

        args = [
            CLI_BINARY,
            "exec",
            "--sandbox",
            "workspace-write",
            "--json",
            "-o",
            str(result_path),
            prompt,
        ]
        # Docs are ambiguous about which of these two the CLI actually reads --
        # setting both is a harmless redundancy, not a real ambiguity risk.
        extra_env = {"CODEX_API_KEY": self._api_key, "OPENAI_API_KEY": self._api_key} if self._api_key else None

        try:
            returncode, stdout, stderr = await run_cli(
                args, cwd=repo_dir, timeout_seconds=timeout, extra_env=extra_env
            )
        except EngineTimeoutError as exc:
            return ChangeAgentResult(success=False, summary=str(exc))
        finally:
            summary = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else ""
            result_path.unlink(missing_ok=True)

        return ChangeAgentResult(
            success=returncode == 0,
            summary=summary or "(codex produced no output)",
            raw_log=f"stdout:\n{stdout}\n\nstderr:\n{stderr}",
            usage=parse_usage(stdout),
        )
