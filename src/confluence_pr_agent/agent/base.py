"""The pluggable interface every code-writing engine implements.

The pipeline (pipeline/orchestrator.py) only ever talks to this interface --
it does not know or care whether the actual work happens via the Claude
Agent SDK, the Cursor CLI, the GitHub Copilot CLI, or anything else you wire
in later. Swapping engines is a config change (CHANGE_AGENT_ENGINE in .env),
not a code change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from confluence_pr_agent.models import ChangeAgentResult, PageDiff


class ChangeEngine(Protocol):
    async def implement_change(self, repo_dir: Path, diff: PageDiff, max_turns: int) -> ChangeAgentResult: ...
