"""ChangeEngine backed by the Claude Agent SDK (which itself shells out to
the `claude` CLI -- see docs/change-engines.md for why that binary has to be
on PATH separately; the SDK does not bundle it).
"""

from __future__ import annotations

import os
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from confluence_pr_agent.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from confluence_pr_agent.models import ChangeAgentResult, PageDiff


class ClaudeCodeEngine:
    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def implement_change(
        self, repo_dir: Path, diff: PageDiff, max_turns: int, retry_context: str | None = None
    ) -> ChangeAgentResult:
        prompt = build_user_prompt(diff, retry_context)

        # Explicit env, not inherited from this process's ambient
        # os.environ -- with multiple users' credentials potentially live
        # in one process, ambient env can't safely stand in for per-run
        # credentials. Starts from a copy of the real environment (PATH,
        # etc. -- the `claude` CLI subprocess still needs those) with just
        # ANTHROPIC_API_KEY overridden to this run's own key.
        options = ClaudeAgentOptions(
            cwd=str(repo_dir),
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            system_prompt=SYSTEM_PROMPT,
            max_turns=max_turns,
            env={**os.environ, "ANTHROPIC_API_KEY": self._api_key} if self._api_key else dict(os.environ),
        )

        log_lines: list[str] = []
        final_summary: str | None = None
        succeeded = False
        usage: dict | None = None

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        log_lines.append(f"[assistant] {block.text}")
                    elif isinstance(block, ToolUseBlock):
                        log_lines.append(f"[tool_use] {block.name} {block.input}")
            elif isinstance(message, ResultMessage):
                succeeded = message.subtype == "success"
                final_summary = message.result
                log_lines.append(f"[result] subtype={message.subtype} reason={message.terminal_reason}")
                usage = {
                    **(message.usage or {}),
                    "total_cost_usd": message.total_cost_usd,
                    "num_turns": message.num_turns,
                    "duration_ms": message.duration_ms,
                }

        return ChangeAgentResult(
            success=succeeded,
            summary=final_summary or "(agent produced no final summary)",
            raw_log="\n".join(log_lines),
            usage=usage,
        )
