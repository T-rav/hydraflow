"""Tests for scripts/audit_prompts.py — AuditTarget dataclass and prompt registry scaffold."""

from __future__ import annotations

from scripts.audit_prompts import AuditTarget, score_leads_with_request

IMPERATIVE_PROMPT = "Classify this issue into one of three categories: ..."
DELAYED_PROMPT = (
    "This is a triage task. A classification is needed. Classify this issue..."
)
BURIED_PROMPT = (
    "Background context. Lots of reading. Many sentences. And finally: classify."
)


def test_audit_target_carries_metadata():
    target = AuditTarget(
        name="triage_build_prompt",
        builder_qualname="triage.Triage._build_prompt_with_stats",
        fixture_path="tests/fixtures/prompts/triage_build_prompt.json",
        category="Triage",
        call_site="src/triage.py:194",
    )
    assert target.name == "triage_build_prompt"
    assert target.category == "Triage"
    assert target.call_site == "src/triage.py:194"


def test_score_leads_with_request_pass_when_first_sentence_has_imperative():
    assert score_leads_with_request(IMPERATIVE_PROMPT) == "Pass"


def test_score_leads_with_request_partial_when_imperative_in_sentence_two_or_three():
    assert score_leads_with_request(DELAYED_PROMPT) == "Partial"


def test_score_leads_with_request_fail_when_imperative_buried_beyond_sentence_three():
    assert score_leads_with_request(BURIED_PROMPT) == "Fail"
