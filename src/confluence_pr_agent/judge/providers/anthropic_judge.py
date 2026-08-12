"""Judge provider backed directly by the Anthropic API (not the claude-agent-sdk
CLI wrapper the claude_code change engine uses -- this is a single evaluation
turn, not an agentic session, so the plain SDK is enough).
"""

from __future__ import annotations

from anthropic import AsyncAnthropic

from confluence_pr_agent.judge.prompts import (
    SYSTEM_PROMPT,
    VERDICT_TOOL_DESCRIPTION,
    VERDICT_TOOL_NAME,
    VERDICT_TOOL_PARAMETERS,
    build_prompt,
)
from confluence_pr_agent.models import ChangeAgentResult, JudgeResult, PageDiff

DEFAULT_MODEL = "claude-sonnet-5"

# Anthropic's API has no forced-JSON response mode; a single tool call with
# tool_choice pinned to it is what guarantees a structured, parseable
# verdict instead of the model narrating its reasoning in free text.
_TOOL = {
    "name": VERDICT_TOOL_NAME,
    "description": VERDICT_TOOL_DESCRIPTION,
    "input_schema": VERDICT_TOOL_PARAMETERS,
}


class AnthropicJudge:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def evaluate(self, diff: PageDiff, change: ChangeAgentResult, code_diff: str) -> JudgeResult:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(diff, change, code_diff)}],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": VERDICT_TOOL_NAME},
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == VERDICT_TOOL_NAME:
                verdict_input = block.input
                return JudgeResult(
                    verdict=verdict_input["verdict"],
                    reasoning=verdict_input["reasoning"],
                    concerns=list(verdict_input.get("concerns") or []),
                )

        # tool_choice pins the model to VERDICT_TOOL_NAME, so this shouldn't
        # happen -- but fail open rather than silently blocking every PR on
        # an SDK surprise.
        return JudgeResult(
            verdict="skipped", reasoning="Judge did not return a structured verdict; proceeding without review."
        )
