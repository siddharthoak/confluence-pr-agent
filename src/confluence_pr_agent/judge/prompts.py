"""Prompt text shared by every judge provider, so switching JUDGE_PROVIDER
changes only which API answers the question, not the question itself.
"""

from __future__ import annotations

from confluence_pr_agent.models import ChangeAgentResult, JudgeCriterion, PageDiff

MAX_CODE_DIFF_CHARS = 60_000

# The fixed set of dimensions the judge scores independently -- (key, label).
# key matches a property name in VERDICT_TOOL_PARAMETERS below and becomes
# JudgeCriterion.key; label is the human-readable row heading rendered in
# the PR rubric table (see orchestrator.py::_build_pr_body).
CRITERIA: list[tuple[str, str]] = [
    ("implements_spec", "Implements the spec change"),
    ("scoped", "Scoped to the change"),
    ("tests_cover_behavior", "Tests cover the new behavior"),
]

SYSTEM_PROMPT = """You are a meticulous senior engineer doing the final review before a pull \
request is opened automatically, with no human in the loop before this point. You are given \
the Confluence spec change an AI coding agent was asked to implement, the actual code diff it \
produced, and the agent's own summary of its work. Judge strictly, based only on the diff -- \
not the summary, which the same agent wrote and may be more flattering than the code.

Score each of these three criteria independently -- do not let one criterion's score influence \
another, and do not soften a score because the diff is "close enough" overall:

1. implements_spec -- does the diff actually implement what the spec change describes, the \
specific behavior requested, not just plausible-looking code nearby?
2. scoped -- is the diff scoped to the change, with no unrelated files touched and no unrelated \
refactors?
3. tests_cover_behavior -- does the diff include or update tests that actually exercise the \
new/changed behavior, not just tests that were already passing?

For each criterion, assign:
- "pass" -- clearly satisfied.
- "warning" -- a real, specific concern worth a human's attention, but not bad enough that this \
PR should be blocked from opening (e.g. tests exist but only weakly exercise the new behavior; \
a minor, defensible scope nit).
- "fail" -- clearly violated, the kind of gap a human reviewer would immediately bounce this PR \
back for (e.g. the described behavior is simply not implemented; the diff touches large unrelated \
areas of the codebase).

You are not deciding whether the PR opens -- it always will. Your scores decide whether it opens \
as a normal PR, a PR flagged with warnings, or a PR flagged as needing rework before merge. When \
genuinely uncertain rather than clearly wrong, prefer "warning" over "fail" -- this review exists \
to give a human reviewer a head start, not to replace their judgment."""

VERDICT_TOOL_NAME = "submit_verdict"

VERDICT_TOOL_DESCRIPTION = "Submit your per-criterion review scores for this code change."

_CRITERION_SCHEMA = {
    "type": "object",
    "properties": {
        "assessment": {"type": "string", "enum": ["pass", "warning", "fail"]},
        "note": {"type": "string", "description": "One sentence, specific to this diff."},
    },
    "required": ["assessment", "note"],
}

VERDICT_TOOL_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "object",
            "properties": {key: _CRITERION_SCHEMA for key, _ in CRITERIA},
            "required": [key for key, _ in CRITERIA],
        },
        "reasoning": {
            "type": "string",
            "description": "2-4 sentences summarizing the overall review, specific to this diff.",
        },
        "concerns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific issues found, across any criterion. Empty if none.",
        },
    },
    "required": ["criteria", "reasoning", "concerns"],
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


def parse_criteria(raw: dict) -> list[JudgeCriterion]:
    """Turns the tool call's `criteria` object (key -> {assessment, note})
    into JudgeCriterion rows, in CRITERIA's fixed display order.
    """
    return [
        JudgeCriterion(key=key, label=label, assessment=raw[key]["assessment"], note=raw[key]["note"])
        for key, label in CRITERIA
    ]


def derive_verdict(criteria: list[JudgeCriterion]) -> str:
    """The overall verdict is computed from criteria, not reported by the
    model directly -- one fixed rule instead of the model's own (possibly
    inconsistent) holistic read of scores it just assigned itself.
    """
    assessments = {c.assessment for c in criteria}
    if "fail" in assessments:
        return "rejected"
    if "warning" in assessments:
        return "approved_with_warnings"
    return "approved"
