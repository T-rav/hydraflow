"""Regression guard for #10423 — discover brief schema didn't match its own grader.

ADR-0107 turned ``DiscoverRunner`` into a general planner-invoked helper: it
now runs for any low-clarity/escalated/route-back issue, not just
user-facing product features. But ``_build_prompt`` kept asking the agent
for a product-strategist brief ("3-4 paragraph executive summary: problem
insight, market landscape, key opportunities") while the
``discover-completeness`` evaluator (§4.10, ``discover_completeness.py``)
grades every brief against a fixed five-section rubric: *Intent*,
*Affected area*, *Acceptance criteria*, *Open questions*, *Known unknowns*.

Nothing in the old prompt ever asked for those headings, so any brief the
agent produced — however good — was structurally guaranteed to fail
criterion 1 (``missing-section:*``). For issue #10419 (an internal ADR/lint
feature, not a product idea), the mismatch was severe enough that the agent
produced no parseable output at all across all 3 bounded retries, and the
runner escalated `discover-stuck` (#10423).

Fix: rewrite ``_build_prompt`` to require the rubric's five named sections
in ``research_brief`` directly, and make the competitor/market research
optional — gated on the issue actually being a user-facing product feature
— instead of the mandatory framing for every issue.

This guard pins that the prompt DiscoverRunner sends actually asks for the
sections its own evaluator checks for, and no longer forces every issue
into a "product strategist" frame.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from discover_runner import DiscoverRunner


def _make_task(issue_id: int, title: str, body: str) -> MagicMock:
    task = MagicMock()
    task.id = issue_id
    task.title = title
    task.body = body
    return task


class TestDiscoverPromptMatchesCompletenessRubric:
    """The requested brief structure must match discover-completeness's rubric."""

    def test_prompt_requires_all_five_rubric_sections(self, config, event_bus) -> None:
        runner = DiscoverRunner(config, event_bus)
        task = _make_task(
            10419,
            "Nudge high-churn bare ADR citations toward :Symbol granularity",
            "A lint/warning in the ADR-index parse path (src/adr_index.py) "
            "or a caretaker check could flag bare citations. (optional, deferred)",
        )

        prompt = runner._build_prompt(task)

        for heading in (
            "### Intent",
            "### Affected area",
            "### Acceptance criteria",
            "### Open questions",
            "### Known unknowns",
        ):
            assert heading in prompt, f"prompt missing required section: {heading}"

    def test_product_research_is_optional_not_mandatory(self, config, event_bus) -> None:
        """The prior prompt forced every issue into a product-strategist frame.

        Engineering issues (like #10419) have no competitors or market
        timing to research — that framing must now be conditional, not the
        agent's primary mission.
        """
        runner = DiscoverRunner(config, event_bus)
        task = _make_task(1, "Internal lint rule", "Add a warning for X.")

        prompt = runner._build_prompt(task)

        assert "senior product strategist" not in prompt
        assert "top PM at Stripe or Figma" not in prompt
        assert "Optional: Product & Market Research" in prompt
        assert "engineering/tooling" in prompt.lower()

    def test_open_questions_instruction_survives_for_ambiguous_issues(
        self, config, event_bus
    ) -> None:
        """Discover-completeness's hid-ambiguity check needs explicit backing."""
        runner = DiscoverRunner(config, event_bus)
        task = _make_task(2, "Maybe add caching", "Not sure if this is worth it.")

        prompt = runner._build_prompt(task)

        assert "hedges" in prompt.lower() or "ambigu" in prompt.lower()
        assert "Maybe add caching" in prompt
