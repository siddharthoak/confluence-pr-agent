from __future__ import annotations

from confluence_pr_agent.jira import story_writer
from confluence_pr_agent.models import PageDiff, PageSnapshot

_STORY = story_writer.JiraStoryContent(
    summary="Support PayPal at checkout",
    description="The spec now requires PayPal as a payment option.",
    acceptance_criteria=["Customer can select PayPal"],
    complexity="M",
    complexity_reason="Touches the payment integration.",
)


def _diff() -> PageDiff:
    page = PageSnapshot(
        page_id="123456", title="Checkout Flow Spec", version=2, body_html="<p>spec v2</p>",
        url="https://example.atlassian.net/wiki/spaces/SD/pages/123456",
    )
    return PageDiff(
        page=page, previous_version=1, diff_text="-old line\n+new line", is_first_seen=False,
        body_checksum="abc123",
    )


def test_fallback_content_has_no_raw_diff_text():
    """The description must read on its own -- the diff belongs in a
    separate Jira comment (pipeline/orchestrator.py), not dumped into the
    one field meant to be readable at a glance.
    """
    content = story_writer._fallback_content(_diff())
    assert "-old line" not in content.description
    assert "+new line" not in content.description
    assert "Checkout Flow Spec" in content.description


async def test_prefers_anthropic_when_judge_provider_is_anthropic_and_key_set(settings, monkeypatch):
    settings.judge_provider = "anthropic"
    settings.anthropic_api_key = "sk-test"
    settings.gemini_api_key = "gemini-test-key"  # present but must not be tried

    async def _fake_anthropic(settings, diff):
        return _STORY

    async def _boom_gemini(settings, diff):
        raise AssertionError("gemini should not be tried when anthropic succeeds")

    monkeypatch.setattr(story_writer, "_generate_anthropic", _fake_anthropic)
    monkeypatch.setattr(story_writer, "_generate_gemini", _boom_gemini)

    result = await story_writer.generate_story_content(settings, _diff())
    assert result is _STORY


async def test_falls_back_to_gemini_when_judge_provider_key_is_missing(settings, monkeypatch):
    settings.judge_provider = "anthropic"
    settings.anthropic_api_key = ""  # not set -- anthropic branch never attempted
    settings.gemini_api_key = "gemini-test-key"

    async def _fake_gemini(settings, diff):
        return _STORY

    monkeypatch.setattr(story_writer, "_generate_gemini", _fake_gemini)

    result = await story_writer.generate_story_content(settings, _diff())
    assert result is _STORY


async def test_falls_back_to_gemini_when_judge_provider_call_fails(settings, monkeypatch):
    settings.judge_provider = "anthropic"
    settings.anthropic_api_key = "sk-test"
    settings.gemini_api_key = "gemini-test-key"

    async def _fail_anthropic(settings, diff):
        raise RuntimeError("anthropic is down")

    async def _fake_gemini(settings, diff):
        return _STORY

    monkeypatch.setattr(story_writer, "_generate_anthropic", _fail_anthropic)
    monkeypatch.setattr(story_writer, "_generate_gemini", _fake_gemini)

    result = await story_writer.generate_story_content(settings, _diff())
    assert result is _STORY


async def test_falls_back_to_plain_content_when_nothing_is_configured(settings):
    settings.judge_provider = "anthropic"
    settings.anthropic_api_key = ""
    settings.openai_api_key = ""
    settings.gemini_api_key = ""

    result = await story_writer.generate_story_content(settings, _diff())
    assert "AI-generated description unavailable" in result.description


async def test_falls_back_to_plain_content_when_gemini_also_fails(settings, monkeypatch):
    settings.judge_provider = "anthropic"
    settings.anthropic_api_key = ""
    settings.gemini_api_key = "gemini-test-key"

    async def _fail_gemini(settings, diff):
        raise RuntimeError("gemini is down")

    monkeypatch.setattr(story_writer, "_generate_gemini", _fail_gemini)

    result = await story_writer.generate_story_content(settings, _diff())
    assert "AI-generated description unavailable" in result.description
