from __future__ import annotations

from confluence_pr_agent.ui.usage_summary import summarize_usage


def test_returns_empty_for_none_or_non_dict():
    assert summarize_usage(None) == {}
    assert summarize_usage("not a dict") == {}
    assert summarize_usage({}) == {}


def test_summarizes_flat_claude_code_shape():
    usage = {
        "input_tokens": 1200,
        "output_tokens": 340,
        "total_cost_usd": 0.0213,
        "num_turns": 6,
        "duration_ms": 45210,
    }

    summary = summarize_usage(usage)

    assert summary["Input tokens"] == "1,200"
    assert summary["Output tokens"] == "340"
    assert summary["Cost (USD)"] == "$0.0213"
    assert summary["Turns"] == "6"
    assert summary["Duration"] == "45,210 ms"


def test_summarizes_nested_gemini_shape():
    usage = {
        "files": {"totalLinesAdded": 88, "totalLinesRemoved": 1},
        "models": {
            "gemini-3-flash-preview": {
                "api": {"totalRequests": 2, "totalLatencyMs": 13050},
                "tokens": {"input": 19881, "candidates": 291},
            },
            "gemini-3.1-flash-lite": {
                "api": {"totalRequests": 1, "totalLatencyMs": 8029},
                "tokens": {"input": 2021, "candidates": 78},
            },
        },
    }

    summary = summarize_usage(usage)

    assert summary["Models used"] == "gemini-3-flash-preview, gemini-3.1-flash-lite"
    assert summary["Input tokens"] == "21,902"
    assert summary["Output tokens"] == "369"
    assert summary["API requests"] == "3"
    assert summary["Total latency"] == "21,079 ms"
    assert summary["Lines changed"] == "+88 / -1"


def test_returns_empty_for_unrecognized_shape():
    assert summarize_usage({"some_field": "some_value"}) == {}
