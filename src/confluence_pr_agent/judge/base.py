"""The interface every judge provider implements -- mirrors agent/base.py's
ChangeEngine so the same "pluggable via config, not code" shape applies to
both halves of the pipeline that talk to an LLM.
"""

from __future__ import annotations

from typing import Protocol

from confluence_pr_agent.models import ChangeAgentResult, JudgeResult, PageDiff


class ChangeJudge(Protocol):
    async def evaluate(self, diff: PageDiff, change: ChangeAgentResult, code_diff: str) -> JudgeResult: ...
