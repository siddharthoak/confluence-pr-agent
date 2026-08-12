from __future__ import annotations

import pytest

from confluence_pr_agent.judge.factory import build_judge, judge_configured
from confluence_pr_agent.judge.providers.anthropic_judge import AnthropicJudge
from confluence_pr_agent.judge.providers.gemini_judge import GeminiJudge
from confluence_pr_agent.judge.providers.openai_judge import OpenAIJudge


@pytest.mark.parametrize(
    "name,expected_type",
    [
        ("anthropic", AnthropicJudge),
        ("Anthropic", AnthropicJudge),  # case-insensitive
        ("openai", OpenAIJudge),
        ("gemini", GeminiJudge),
    ],
)
def test_build_judge_dispatches_by_name(name, expected_type, settings):
    settings.judge_provider = name
    # AnthropicJudge/OpenAIJudge/GeminiJudge all require a non-empty key
    # just to construct their underlying client -- settings.anthropic_api_key
    # is already set by the shared fixture, but openai_api_key/gemini_api_key
    # aren't (this test previously only passed for "openai" because a real
    # developer .env's OPENAI_API_KEY was silently leaking through the old,
    # less isolated fixture).
    settings.openai_api_key = "test-openai-key"
    settings.gemini_api_key = "test-gemini-key"
    assert isinstance(build_judge(settings), expected_type)


def test_build_judge_rejects_unknown_provider(settings):
    settings.judge_provider = "some-other-tool"
    with pytest.raises(ValueError, match="Unknown JUDGE_PROVIDER"):
        build_judge(settings)


def test_judge_configured_true_when_matching_key_present(settings):
    settings.judge_provider = "anthropic"
    settings.anthropic_api_key = "sk-test"
    assert judge_configured(settings) is True


def test_judge_configured_false_when_matching_key_missing(settings):
    settings.judge_provider = "openai"
    settings.openai_api_key = ""
    assert judge_configured(settings) is False


def test_judge_configured_ignores_the_other_providers_key(settings):
    """A key for a *different* provider being set must not count -- e.g.
    ANTHROPIC_API_KEY being set (for the claude_code change engine) must not
    make judge_configured() true when JUDGE_PROVIDER is "openai".
    """
    settings.judge_provider = "openai"
    settings.anthropic_api_key = "sk-anthropic-test"
    settings.openai_api_key = ""
    assert judge_configured(settings) is False
