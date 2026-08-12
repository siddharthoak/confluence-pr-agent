"""Prompt text shared by every judge provider, so switching JUDGE_PROVIDER
changes only which API answers the question, not the question itself.
"""

from __future__ import annotations

from confluence_pr_agent.models import ChangeAgentResult, PageDiff

MAX_CODE_DIFF_CHARS = 60_000

SYSTEM_PROMPT = """You are a meticulous senior engineer doing the final review before a pull \
request is opened automatically, with no human in the loop before this point. You are given \
the Confluence spec change an AI coding agent was asked to implement, the actual code diff it \
produced, and the agent's own summary of its work. Judge strictly, based only on the diff -- \
not the summary, which the same agent wrote and may be more flattering than the code:

1. Does the diff actually implement what the spec change describes -- the specific behavior \
requested, not just plausible-looking code nearby?
2. Is the diff scoped to the change -- no unrelated files touched, no unrelated refactors?
3. Does the diff include or update tests that actually exercise the new/changed behavior?

Reject if any of these are clearly violated. Approve if you're confident a human reviewer would \
not immediately bounce this PR back for missing or wrong behavior. When genuinely uncertain \
rather than clearly wrong, approve -- this gate exists to catch obvious misses, not to replace \
human review."""

VERDICT_TOOL_NAME = "submit_verdict"

VERDICT_TOOL_DESCRIPTION = "Submit your review verdict for this code change."

VERDICT_TOOL_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approved", "rejected"]},
        "reasoning": {
            "type": "string",
            "description": "2-4 sentences explaining the verdict, specific to this diff.",
        },
        "concerns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific issues found. Empty if approved with no notes.",
        },
    },
    "required": ["verdict", "reasoning", "concerns"],
}


def build_prompt(diff: PageDiff, change: ChangeAgentResult, code_diff: str) -> str:
    if len(code_diff) > MAX_CODE_DIFF_CHARS:
        code_diff = code_diff[:MAX_CODE_DIFF_CHARS] + "\n... (diff truncated)"
    return (
        f"Confluence spec page: {diff.page.title}\n"
        f"Page version: {diff.previous_version} -> {diff.page.version}\n\n"
        f"--- Spec change (unified diff of the page's plain-text content) ---\n{diff.diff_text}\n\n"
        f"--- Agent's own summary of the code change it made ---\n{change.summary}\n\n"
        f"--- Actual code diff produced ---\n{code_diff or '(no diff text available)'}\n"
    )
