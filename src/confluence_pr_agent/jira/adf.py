"""Atlassian Document Format helpers.

Jira Cloud's REST API v3 requires `description`/comment bodies as ADF (a
structured JSON document), not plain strings -- unlike Confluence's storage
format, there's no plain-text shortcut. These are minimal, hand-rolled
builders (paragraphs, a heading, a bullet list) good enough for
LLM-generated prose, not a full markdown-to-ADF converter.
"""

from __future__ import annotations


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}] if text else []}


def text_to_adf(text: str) -> dict:
    """One paragraph node per blank-line-separated block."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    content = [_paragraph(p) for p in paragraphs] or [_paragraph("")]
    return {"type": "doc", "version": 1, "content": content}


def build_story_description_adf(description: str, acceptance_criteria: list[str]) -> dict:
    content = [_paragraph(p.strip()) for p in description.split("\n\n") if p.strip()]

    if acceptance_criteria:
        content.append(
            {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Acceptance Criteria"}]}
        )
        content.append(
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [_paragraph(ac)]} for ac in acceptance_criteria
                ],
            }
        )

    return {"type": "doc", "version": 1, "content": content or [_paragraph("")]}
