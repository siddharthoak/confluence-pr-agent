"""Picks a ChangeJudge implementation by name (JUDGE_PROVIDER in .env) --
mirrors agent/factory.py's build_change_engine. The judge is independent of
CHANGE_AGENT_ENGINE on purpose: it's meant to be a second opinion on
whatever engine wrote the change, not the same model grading its own work.

Adding a provider: implement ChangeJudge (judge/base.py) in
judge/providers/, register it in both maps below. Nothing else in the
pipeline changes.
"""

from __future__ import annotations

from confluence_pr_agent.config import Settings
from confluence_pr_agent.judge.base import ChangeJudge

_PROVIDERS = ("anthropic", "openai")

# Which Settings field holds the API key for each provider -- used by
# judge_configured() below so the orchestrator can skip the review (instead
# of letting a real API call fail) when the operator picked a provider but
# never set its key, same as the SENDGRID_API_KEY check for the email step.
_CREDENTIAL_FIELD = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
}


def build_judge(settings: Settings) -> ChangeJudge:
    provider = settings.judge_provider.strip().lower()

    if provider == "anthropic":
        from confluence_pr_agent.judge.providers.anthropic_judge import DEFAULT_MODEL, AnthropicJudge

        return AnthropicJudge(api_key=settings.anthropic_api_key, model=settings.judge_model or DEFAULT_MODEL)

    if provider == "openai":
        from confluence_pr_agent.judge.providers.openai_judge import DEFAULT_MODEL, OpenAIJudge

        return OpenAIJudge(api_key=settings.openai_api_key, model=settings.judge_model or DEFAULT_MODEL)

    raise ValueError(f"Unknown JUDGE_PROVIDER '{settings.judge_provider}' -- expected one of {_PROVIDERS}")


def judge_configured(settings: Settings) -> bool:
    """Whether the credential the selected judge provider needs is actually
    set. False means the pipeline should skip the review rather than call
    it -- see pipeline/orchestrator.py.
    """
    provider = settings.judge_provider.strip().lower()
    field = _CREDENTIAL_FIELD.get(provider)
    return bool(field and getattr(settings, field))
