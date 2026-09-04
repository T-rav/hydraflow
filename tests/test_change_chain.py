"""Unit tests for the per-change artifact chain model (ADR-0149)."""

from pathlib import Path

import pytest

from change_chain import (
    ChainArtifact,
    ChainRecord,
    archive_root,
    chain_dir,
    digest,
    render_criteria,
    render_evidence,
    render_intent,
    render_plan,
    resolve_chain_dir,
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


def test_render_criteria_lists_each_acceptance_criterion():
    rendered = render_criteria(7, ["returns 404 for an unknown id"], "PASS", [])

    assert "- returns 404 for an unknown id" in rendered


def test_render_criteria_records_the_judge_verdict():
    rendered = render_criteria(7, ["a criterion"], "CONCERNS", [])

    assert "CONCERNS" in rendered


def test_render_criteria_says_so_when_no_criteria_were_drafted():
    rendered = render_criteria(7, [], "PASS", [])

    assert "_(none drafted)_" in rendered


def test_render_criteria_lists_forwarded_concerns():
    rendered = render_criteria(7, ["a criterion"], "CONCERNS", ["unresolved thing"])

    assert "- unresolved thing" in rendered


def test_render_criteria_omits_the_concerns_heading_when_there_are_none():
    rendered = render_criteria(7, ["a criterion"], "PASS", [])

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


def test_the_stream_payload_never_carries_a_rendered_body():
    """Bodies are scrubbed by AuditChain and would break their own digests."""
    record = ChainRecord(
        issue_number=7,
        digests={ChainArtifact.PLAN: "b" * 64},
        rendered={ChainArtifact.PLAN: "the body"},
        recorded_at="2026-09-03T00:00:00Z",
    )

    assert "rendered" not in record.to_json_dict()


def test_the_anchor_round_trips_through_its_json_form():
    record = ChainRecord(
        issue_number=7,
        digests={ChainArtifact.PLAN: "b" * 64},
        rendered={},
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


def test_resolve_finds_a_live_change(tmp_path: Path):
    chain_dir(tmp_path, 7).mkdir(parents=True)

    assert resolve_chain_dir(tmp_path, 7) == chain_dir(tmp_path, 7)


def test_resolve_finds_a_change_folded_into_the_quarterly_archive(tmp_path: Path):
    archived = archive_root(tmp_path) / "2026-Q3" / "issue-7"
    archived.mkdir(parents=True)

    assert resolve_chain_dir(tmp_path, 7) == archived


def test_resolve_prefers_the_live_directory_over_an_archived_one(tmp_path: Path):
    (archive_root(tmp_path) / "2026-Q3" / "issue-7").mkdir(parents=True)
    chain_dir(tmp_path, 7).mkdir(parents=True)

    assert resolve_chain_dir(tmp_path, 7) == chain_dir(tmp_path, 7)


def test_resolve_returns_none_when_the_change_has_no_chain(tmp_path: Path):
    assert resolve_chain_dir(tmp_path, 7) is None


def test_resolve_searches_the_newest_quarter_first(tmp_path: Path):
    (archive_root(tmp_path) / "2025-Q1" / "issue-7").mkdir(parents=True)
    newest = archive_root(tmp_path) / "2026-Q3" / "issue-7"
    newest.mkdir(parents=True)

    assert resolve_chain_dir(tmp_path, 7) == newest


def test_resolve_ignores_a_stray_file_in_the_archive_root(tmp_path: Path):
    archive_root(tmp_path).mkdir(parents=True)
    (archive_root(tmp_path) / "stray.md").write_text("not a quarter")

    assert resolve_chain_dir(tmp_path, 7) is None
