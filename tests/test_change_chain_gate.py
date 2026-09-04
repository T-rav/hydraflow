"""Chain verification: presence, digest and scope (ADR-0149).

Every finding class gets a test that reddens when the check is removed —
verified by mutation, not by inspection. The compaction cases matter most:
a gate that stops finding an archived change reports nothing, which reads
exactly like a clean change.
"""

from pathlib import Path

import pytest

from change_chain import (
    ChainArtifact,
    ChainRecord,
    archive_root,
    chain_dir,
    digest,
    render_plan,
)
from change_chain_gate import (
    FINDING_DIGEST_MISMATCH,
    FINDING_MISSING,
    FINDING_NO_CHAIN,
    FINDING_SCOPE_DEPARTURE,
    verify_chain,
)

_AT = "2026-09-03T00:00:00Z"


def _seed(root: Path, issue: int, plan_body: str, *, into: Path | None = None):
    """Write a plan file and return the record that anchors it."""
    directory = into if into is not None else chain_dir(root, issue)
    directory.mkdir(parents=True, exist_ok=True)
    rendered = render_plan(issue, plan_body, "s")
    (directory / "plan.md").write_text(rendered)
    return ChainRecord(
        issue_number=issue,
        digests={ChainArtifact.PLAN: digest(rendered)},
        rendered={ChainArtifact.PLAN: rendered},
        recorded_at=_AT,
    )


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def test_a_matching_chain_produces_no_findings(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")

    assert verify_chain(tmp_path, 7, record, ["src/a.py"]) == ()


def test_an_unanchored_change_is_a_finding(tmp_path):
    findings = verify_chain(tmp_path, 7, None, ["src/a.py"])

    assert _codes(findings) == [FINDING_NO_CHAIN]


def test_a_change_with_no_chain_directory_is_a_finding(tmp_path):
    record = ChainRecord(
        issue_number=7,
        digests={ChainArtifact.PLAN: "a" * 64},
        rendered={},
        recorded_at=_AT,
    )

    assert _codes(verify_chain(tmp_path, 7, record, [])) == [FINDING_MISSING]


def test_a_missing_plan_file_is_a_finding(tmp_path):
    chain_dir(tmp_path, 7).mkdir(parents=True)
    record = ChainRecord(
        issue_number=7,
        digests={ChainArtifact.PLAN: "a" * 64},
        rendered={},
        recorded_at=_AT,
    )

    assert _codes(verify_chain(tmp_path, 7, record, [])) == [FINDING_MISSING]


def test_a_tampered_plan_file_is_a_finding(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")
    (chain_dir(tmp_path, 7) / "plan.md").write_text("forged")

    assert _codes(verify_chain(tmp_path, 7, record, ["src/a.py"])) == [
        FINDING_DIGEST_MISMATCH
    ]


def test_a_single_byte_edit_is_caught(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")
    path = chain_dir(tmp_path, 7) / "plan.md"
    path.write_text(path.read_text() + " ")

    assert FINDING_DIGEST_MISMATCH in _codes(verify_chain(tmp_path, 7, record, []))


def test_a_file_the_plan_never_named_is_a_scope_finding(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")

    findings = verify_chain(tmp_path, 7, record, ["src/a.py", "src/unplanned.py"])

    assert _codes(findings) == [FINDING_SCOPE_DEPARTURE]


def test_the_scope_finding_names_the_offending_file(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")

    findings = verify_chain(tmp_path, 7, record, ["src/unplanned.py"])

    assert "src/unplanned.py" in findings[0].detail


def test_the_changes_own_chain_directory_is_never_a_scope_departure(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")

    findings = verify_chain(
        tmp_path, 7, record, ["src/a.py", "docs/changes/issue-7/plan.md"]
    )

    assert findings == ()


def test_another_changes_chain_directory_is_a_scope_departure(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")

    findings = verify_chain(
        tmp_path, 7, record, ["src/a.py", "docs/changes/issue-8/plan.md"]
    )

    assert _codes(findings) == [FINDING_SCOPE_DEPARTURE]


def test_a_plan_naming_a_file_by_basename_accepts_its_full_path(tmp_path):
    record = _seed(tmp_path, 7, "edit config.py")

    assert verify_chain(tmp_path, 7, record, ["src/config.py"]) == ()


def test_an_archived_change_is_still_verified(tmp_path):
    archived = archive_root(tmp_path) / "2026-Q3" / "issue-7"
    record = _seed(tmp_path, 7, "touch src/a.py", into=archived)

    assert verify_chain(tmp_path, 7, record, ["src/a.py"]) == ()


def test_a_tampered_archived_change_is_still_caught(tmp_path):
    archived = archive_root(tmp_path) / "2026-Q3" / "issue-7"
    record = _seed(tmp_path, 7, "touch src/a.py", into=archived)
    (archived / "plan.md").write_text("forged")

    assert _codes(verify_chain(tmp_path, 7, record, [])) == [FINDING_DIGEST_MISMATCH]


def test_a_record_in_its_stream_form_is_accepted(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")

    assert verify_chain(tmp_path, 7, record.to_json_dict(), ["src/a.py"]) == ()


@pytest.mark.parametrize("artifact", list(ChainArtifact))
def test_every_artifact_is_checked_for_presence(tmp_path, artifact):
    chain_dir(tmp_path, 7).mkdir(parents=True)
    record = ChainRecord(
        issue_number=7,
        digests={artifact: "a" * 64},
        rendered={},
        recorded_at=_AT,
    )

    assert _codes(verify_chain(tmp_path, 7, record, [])) == [FINDING_MISSING]


def test_an_artifact_the_charter_requires_but_nothing_anchored_is_a_finding(tmp_path):
    """Passing the declaration is what makes it mean anything."""
    record = _seed(tmp_path, 7, "touch src/a.py")

    findings = verify_chain(
        tmp_path, 7, record, ["src/a.py"], required=("plan", "intent")
    )

    assert [f.code for f in findings] == [FINDING_MISSING]


def test_the_finding_names_the_missing_required_artifact(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")

    findings = verify_chain(tmp_path, 7, record, [], required=("intent",))

    assert "intent.md" in findings[0].detail


def test_nothing_is_required_when_the_charter_declares_nothing(tmp_path):
    record = _seed(tmp_path, 7, "touch src/a.py")

    assert verify_chain(tmp_path, 7, record, ["src/a.py"], required=()) == ()
