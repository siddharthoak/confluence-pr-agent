"""Judge provider backed by the Gemini API (google-genai SDK) -- independent
of the gemini change engine (agent/engines/gemini_cli.py), which shells out
to the `gemini` CLI rather than calling the API directly. Also independent
of whatever model that CLI uses internally for code changes, so a user whose
CHANGE_AGENT_ENGINE is gemini can still pick a distinct Gemini model here
for review, same as picking Anthropic/OpenAI would be.
"""

from __future__ import annotations

import json

from google import genai
from google.genai import types

from confluence_pr_agent.judge.prompts import (
    SYSTEM_PROMPT,
    VERDICT_TOOL_PARAMETERS,
    build_prompt,
    derive_verdict,
    parse_criteria,
)
from confluence_pr_agent.models import ChangeAgentResult, JudgeResult, PageDiff

DEFAULT_MODEL = "gemini-2.5-pro"


class GeminiJudge:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def evaluate(self, diff: PageDiff, change: ChangeAgentResult, code_diff: str) -> JudgeResult:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=build_prompt(diff, change, code_diff),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                # response_json_schema (not the stricter response_schema, which
                # wants a genai.types.Schema object) accepts the same plain
                # JSON-schema dict already used for the Anthropic/OpenAI tool
                # definitions -- one schema, three providers.
                response_mime_type="application/json",
                response_json_schema=VERDICT_TOOL_PARAMETERS,
            ),
        )
        if not response.text:
            return JudgeResult(
                verdict="skipped", reasoning="Judge did not return a structured verdict; proceeding without review."
            )

        verdict_input = json.loads(response.text)
        criteria = parse_criteria(verdict_input["criteria"])
        return JudgeResult(
            verdict=derive_verdict(criteria),
            reasoning=verdict_input["reasoning"],
            concerns=list(verdict_input.get("concerns") or []),
            criteria=criteria,
        )
