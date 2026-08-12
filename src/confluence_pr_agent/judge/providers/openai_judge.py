"""Judge provider backed by the OpenAI API. Independent of the codex change
engine (agent/engines/codex_cli.py), which shells out to the `codex` CLI
rather than calling the API directly -- this is a single evaluation turn,
so the plain SDK is enough here too.
"""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from confluence_pr_agent.judge.prompts import (
    SYSTEM_PROMPT,
    VERDICT_TOOL_DESCRIPTION,
    VERDICT_TOOL_NAME,
    VERDICT_TOOL_PARAMETERS,
    build_prompt,
    derive_verdict,
    parse_criteria,
)
from confluence_pr_agent.models import ChangeAgentResult, JudgeResult, PageDiff

DEFAULT_MODEL = "gpt-4.1"

_TOOL = {
    "type": "function",
    "function": {
        "name": VERDICT_TOOL_NAME,
        "description": VERDICT_TOOL_DESCRIPTION,
        "parameters": VERDICT_TOOL_PARAMETERS,
    },
}


class OpenAIJudge:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def evaluate(self, diff: PageDiff, change: ChangeAgentResult, code_diff: str) -> JudgeResult:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(diff, change, code_diff)},
            ],
            tools=[_TOOL],
            tool_choice={"type": "function", "function": {"name": VERDICT_TOOL_NAME}},
        )

        for call in response.choices[0].message.tool_calls or []:
            if call.function.name == VERDICT_TOOL_NAME:
                verdict_input = json.loads(call.function.arguments)
                criteria = parse_criteria(verdict_input["criteria"])
                return JudgeResult(
                    verdict=derive_verdict(criteria),
                    reasoning=verdict_input["reasoning"],
                    concerns=list(verdict_input.get("concerns") or []),
                    criteria=criteria,
                )

        # tool_choice pins the model to VERDICT_TOOL_NAME, so this shouldn't
        # happen -- but fail open rather than silently blocking every PR on
        # an SDK surprise.
        return JudgeResult(
            verdict="skipped", reasoning="Judge did not return a structured verdict; proceeding without review."
        )
