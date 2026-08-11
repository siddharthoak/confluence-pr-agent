"""Renders a unified-diff string as colored HTML for the run detail page --
the Confluence spec diff the agent was actually prompted with. Not
redundant with the GitHub PR link: that shows the resulting code diff,
this shows the spec-side input that produced it, which exists nowhere else.

Builds the HTML directly in Python (escaping each line's text explicitly)
rather than looping in Jinja, since getting whitespace exactly right inside
a <pre> block via template block tags is fragile -- this way the string is
exact by construction and the only "trust" the template extends is via
the |safe filter on a string this module fully controls.
"""

from __future__ import annotations

from html import escape


def _classify(line: str) -> str:
    if line.startswith("+++") or line.startswith("---"):
        return "diff-meta"
    if line.startswith("+"):
        return "diff-add"
    if line.startswith("-"):
        return "diff-remove"
    if line.startswith("@@"):
        return "diff-hunk"
    return "diff-context"


def render_diff_html(diff_text: str) -> str:
    lines = []
    for line in diff_text.splitlines():
        lines.append(f'<span class="{_classify(line)}">{escape(line)}</span>')
    return "\n".join(lines)
