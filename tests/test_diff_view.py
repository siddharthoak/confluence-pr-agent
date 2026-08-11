from __future__ import annotations

from confluence_pr_agent.ui.diff_view import render_diff_html


def test_classifies_added_removed_hunk_meta_and_context_lines():
    diff_text = "\n".join(
        [
            "--- Spec (v1)",
            "+++ Spec (v2)",
            "@@ -1,2 +1,3 @@",
            " Checkout must support credit card payments.",
            "+Checkout must support PayPal payments.",
            "-Checkout must support cash on delivery.",
        ]
    )

    html = render_diff_html(diff_text)

    assert '<span class="diff-meta">--- Spec (v1)</span>' in html
    assert '<span class="diff-meta">+++ Spec (v2)</span>' in html
    assert '<span class="diff-hunk">@@ -1,2 +1,3 @@</span>' in html
    assert '<span class="diff-context"> Checkout must support credit card payments.</span>' in html
    assert '<span class="diff-add">+Checkout must support PayPal payments.</span>' in html
    assert '<span class="diff-remove">-Checkout must support cash on delivery.</span>' in html


def test_escapes_html_special_characters_in_diff_content():
    html = render_diff_html("+<script>alert('x')</script>")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_preserves_line_order_and_count():
    diff_text = "line one\nline two\nline three"

    html = render_diff_html(diff_text)

    assert html.index("line one") < html.index("line two") < html.index("line three")
    assert html.count("<span") == 3
