"""Tests for the discover runner — product research agent."""

from __future__ import annotations

from discover_runner import _DISCOVER_END, _DISCOVER_START, DiscoverRunner
from human_steering import fenced_steering_guidance


class TestExtractResult:
    def test_extracts_valid_json(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        transcript = f"""Some preamble text.

{_DISCOVER_START}

```json
{{
  "issue_number": 42,
  "research_brief": "Calendly dominates scheduling but lacks group features.",
  "competitors": ["Calendly — market leader", "Cal.com — open source"],
  "user_needs": ["Group scheduling", "Privacy-first approach"],
  "opportunities": ["Open source alternative with group focus"]
}}
```

{_DISCOVER_END}

Some trailing text."""

        result = runner._extract_result(transcript, 42)

        assert result is not None
        assert result.issue_number == 42
        assert "Calendly dominates" in result.research_brief
        assert len(result.competitors) == 2
        assert len(result.user_needs) == 2
        assert len(result.opportunities) == 1

    def test_returns_none_without_markers(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        result = runner._extract_result("No markers here", 42)
        assert result is None

    def test_returns_none_with_invalid_json(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        transcript = f"{_DISCOVER_START}\n```json\n{{invalid}}\n```\n{_DISCOVER_END}"
        result = runner._extract_result(transcript, 42)
        assert result is None


class TestExtractRawBrief:
    def test_extracts_text_between_markers(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        transcript = f"{_DISCOVER_START}\nSome raw research text.\n{_DISCOVER_END}"
        result = runner._extract_raw_brief(transcript)
        assert result == "Some raw research text."

    def test_returns_empty_without_markers(self) -> None:
        runner = DiscoverRunner.__new__(DiscoverRunner)
        result = runner._extract_raw_brief("No markers")
        assert result == ""


class TestBuildPrompt:
    def test_prompt_includes_issue_details(self, config, event_bus) -> None:
        from unittest.mock import MagicMock

        runner = DiscoverRunner(config, event_bus)
        task = MagicMock()
        task.id = 42
        task.title = "Build a better Calendly"
        task.body = "I want a scheduling tool"

        prompt = runner._build_prompt(task)

        assert "Build a better Calendly" in prompt
        assert "I want a scheduling tool" in prompt
        assert "DISCOVER_START" in prompt
        assert "DISCOVER_END" in prompt
        assert "competitors" in prompt.lower()
        assert "user_needs" in prompt.lower()

    def test_folds_fenced_human_steering_guidance(self, config, event_bus) -> None:
        """ADR-0099 #4 — live operator guidance is folded in FENCED.

        This is the first of discover's two prompt-construction sites
        (the second being the ``discover-completeness`` evaluator prompt,
        ``build_discover_completeness_prompt``). Guidance must reach the
        prompt only via ``fenced_steering_guidance`` — never as raw
        comment text (ADR-0092 fence invariant).
        """
        from unittest.mock import MagicMock

        runner = DiscoverRunner(config, event_bus)
        task = MagicMock()
        task.id = 42
        task.title = "Build a better Calendly"
        task.body = "I want a scheduling tool"

        guidance = "Prioritize the enterprise SSO angle over consumer features."
        prompt = runner._build_prompt(task, guidance=guidance)

        assert "## Human Steering Guidance" in prompt
        assert fenced_steering_guidance(guidance) in prompt

    def test_empty_guidance_produces_no_steering_section(
        self, config, event_bus
    ) -> None:
        """No guidance posted -> no steering section (unchanged behavior)."""
        from unittest.mock import MagicMock

        runner = DiscoverRunner(config, event_bus)
        task = MagicMock()
        task.id = 42
        task.title = "Build a better Calendly"
        task.body = "I want a scheduling tool"

        prompt = runner._build_prompt(task, guidance="")

        assert "## Human Steering Guidance" not in prompt
