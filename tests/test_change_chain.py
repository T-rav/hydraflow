"""Unit tests for the per-change artifact chain model (ADR-0149)."""

from pathlib import Path

import pytest

from change_chain import (
    ChainArtifact,
    ChainRecord,
    chain_dir,
    digest,
    render_evidence,
    render_intent,
    render_plan,
    render_spec,
)


def test_digest_is_sha256_of_utf8_bytes():
    assert digest("hello") == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_digest_distinguishes_a_one_byte_change():
    assert digest("hello") != digest("hellp")


def test_render_plan_is_byte_stable_across_calls():
    first = render_plan(7, "step one", "does a thing")
    second = render_plan(7, "step one", "does a thing")

    assert first == second


def test_render_plan_embeds_the_issue_number():
    assert "#7" in render_plan(7, "step one", "does a thing")


def test_render_plan_matches_the_legacy_planner_format():
    expected = "# Plan for Issue #7\n\nstep one\n\n---\n**Summary:** does a thing\n"

    assert render_plan(7, "step one", "does a thing") == expected


def test_render_intent_is_byte_stable_across_calls():
    first = render_intent(7, "A title", "A body", "2026-09-03T00:00:00Z")
    second = render_intent(7, "A title", "A body", "2026-09-03T00:00:00Z")

    assert first == second


def test_render_intent_carries_the_issue_body():
    rendered = render_intent(7, "A title", "The body text", "2026-09-03T00:00:00Z")

    assert "The body text" in rendered


def test_render_spec_lists_each_acceptance_criterion():
    rendered = render_spec(7, ["returns 404 for an unknown id"], "PASS", [])

    assert "- returns 404 for an unknown id" in rendered


def test_render_spec_records_the_judge_verdict():
    rendered = render_spec(7, ["a criterion"], "CONCERNS", [])

    assert "CONCERNS" in rendered


def test_render_spec_says_so_when_no_criteria_were_drafted():
    rendered = render_spec(7, [], "PASS", [])

    assert "_(none drafted)_" in rendered


def test_render_spec_lists_forwarded_concerns():
    rendered = render_spec(7, ["a criterion"], "CONCERNS", ["unresolved thing"])

    assert "- unresolved thing" in rendered


def test_render_spec_omits_the_concerns_heading_when_there_are_none():
    rendered = render_spec(7, ["a criterion"], "PASS", [])

    assert "Concerns forwarded unresolved" not in rendered


def test_render_evidence_names_the_approver_role():
    rendered = render_evidence(7, approver_role="delegated-bot", chain_position=4)

    assert "delegated-bot" in rendered


def test_chain_dir_is_under_docs_changes():
    assert chain_dir(Path("/repo"), 7) == Path("/repo/docs/changes/issue-7")


def test_chain_record_carries_a_digest_per_artifact():
    record = ChainRecord(
        issue_number=7,
        digests={ChainArtifact.INTENT: "a" * 64, ChainArtifact.PLAN: "b" * 64},
        rendered={},
        recorded_at="2026-09-03T00:00:00Z",
    )

    assert record.digests[ChainArtifact.PLAN] == "b" * 64


def test_chain_record_json_keys_are_plain_strings():
    record = ChainRecord(
        issue_number=7,
        digests={ChainArtifact.PLAN: "b" * 64},
        rendered={ChainArtifact.PLAN: "body"},
        recorded_at="2026-09-03T00:00:00Z",
    )

    assert record.to_json_dict()["digests"] == {"plan": "b" * 64}


def test_chain_record_json_carries_the_rendered_bodies():
    record = ChainRecord(
        issue_number=7,
        digests={ChainArtifact.PLAN: "b" * 64},
        rendered={ChainArtifact.PLAN: "the body"},
        recorded_at="2026-09-03T00:00:00Z",
    )

    assert record.to_json_dict()["rendered"] == {"plan": "the body"}


def test_chain_record_round_trips_through_its_json_form():
    record = ChainRecord(
        issue_number=7,
        digests={ChainArtifact.PLAN: "b" * 64},
        rendered={ChainArtifact.PLAN: "the body"},
        recorded_at="2026-09-03T00:00:00Z",
    )

    assert ChainRecord.from_json_dict(record.to_json_dict()) == record


def test_from_json_dict_ignores_an_unknown_artifact_name():
    payload = {
        "issue_number": 7,
        "digests": {"plan": "b" * 64, "nonsense": "c" * 64},
        "rendered": {},
        "recorded_at": "2026-09-03T00:00:00Z",
    }

    assert ChainArtifact.PLAN in ChainRecord.from_json_dict(payload).digests


@pytest.mark.parametrize("artifact", list(ChainArtifact))
def test_every_artifact_value_is_a_safe_filename_stem(artifact: ChainArtifact):
    assert artifact.value.isalpha()
