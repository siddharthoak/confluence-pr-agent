"""Turns a raw per-engine `usage` dict into a small label/value table for
display. Presentation-only -- the full raw dict is always still available
(rendered separately, in an accordion) for anyone who wants everything.

Every engine's CLI reports usage differently, if at all (see
docs/change-engines.md), so this is deliberately best-effort: it recognizes
the shapes actually observed from claude_code (flat keys) and
gemini/antigravity (nested per-model "models" dict), and quietly produces
nothing for shapes it doesn't recognize rather than guessing at fields.
"""

from __future__ import annotations


def summarize_usage(usage: dict | None) -> dict[str, str]:
    if not isinstance(usage, dict):
        return {}

    summary: dict[str, str] = {}

    # Flat shape (claude_code: Claude API usage keys + fields this codebase adds itself)
    flat_fields = [
        ("input_tokens", "Input tokens"),
        ("output_tokens", "Output tokens"),
        ("cache_creation_input_tokens", "Cache creation tokens"),
        ("cache_read_input_tokens", "Cache read tokens"),
        ("total_cost_usd", "Cost (USD)"),
        ("num_turns", "Turns"),
        ("duration_ms", "Duration"),
    ]
    for key, label in flat_fields:
        value = usage.get(key)
        if value is None:
            continue
        if key == "total_cost_usd":
            summary[label] = f"${value:.4f}"
        elif key == "duration_ms":
            summary[label] = f"{value:,} ms"
        elif isinstance(value, (int, float)):
            summary[label] = f"{value:,}"
        else:
            summary[label] = str(value)

    # Nested per-model shape (gemini / antigravity: {"models": {name: {"api": {...}, "tokens": {...}}}})
    models = usage.get("models")
    if isinstance(models, dict) and models:
        total_input = total_output = total_requests = total_latency_ms = 0
        for model_data in models.values():
            if not isinstance(model_data, dict):
                continue
            tokens = model_data.get("tokens") or {}
            api = model_data.get("api") or {}
            total_input += tokens.get("input") or 0
            total_output += tokens.get("candidates") or 0
            total_requests += api.get("totalRequests") or 0
            total_latency_ms += api.get("totalLatencyMs") or 0

        summary["Models used"] = ", ".join(sorted(models.keys()))
        if total_input or total_output:
            summary["Input tokens"] = f"{total_input:,}"
            summary["Output tokens"] = f"{total_output:,}"
        if total_requests:
            summary["API requests"] = f"{total_requests:,}"
        if total_latency_ms:
            summary["Total latency"] = f"{total_latency_ms:,} ms"

    files = usage.get("files")
    if isinstance(files, dict):
        added = files.get("totalLinesAdded")
        removed = files.get("totalLinesRemoved")
        if added is not None or removed is not None:
            summary["Lines changed"] = f"+{added or 0} / -{removed or 0}"

    return summary
