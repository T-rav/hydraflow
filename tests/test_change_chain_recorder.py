"""Anchoring a change's plan-time chain on CH-1 (ADR-0149)."""

import json

import pytest

from audit_chain import verify_file
from change_chain import ChainArtifact, digest, render_plan
from change_chain_recorder import build_record, record_chain
from models import Task
from plan_phase_adversarial import CriteriaDraft
from tests.helpers import ConfigFactory

_AT = "2026-09-03T00:00:00Z"


def _task(number: int = 7) -> Task:
    return Task(id=number, title="Add a thing", body="Please add it.")


def _draft() -> CriteriaDraft:
    return CriteriaDraft(
        criteria=("returns 404 for an unknown id",),
        judge_verdict="PASS",
        forwarded_concerns=(),
    )


@pytest.fixture
def config():
    return ConfigFactory.create()


def test_build_record_anchors_intent_and_plan_without_a_draft():
    record = build_record(_task(), "step one", "does a thing", None, recorded_at=_AT)

    assert set(record.digests) == {ChainArtifact.INTENT, ChainArtifact.PLAN}


def test_build_record_anchors_criteria_when_a_draft_exists():
    record = build_record(
        _task(), "step one", "does a thing", _draft(), recorded_at=_AT
    )

    assert ChainArtifact.CRITERIA in record.digests


def test_the_plan_digest_matches_the_rendered_plan():
    record = build_record(_task(), "step one", "does a thing", None, recorded_at=_AT)

    assert record.digests[ChainArtifact.PLAN] == digest(
        render_plan(7, "step one", "does a thing")
    )


def test_every_digest_matches_its_own_rendered_body():
    record = build_record(
        _task(), "step one", "does a thing", _draft(), recorded_at=_AT
    )

    assert all(
        digest(record.rendered[artifact]) == anchored
        for artifact, anchored in record.digests.items()
    )


def test_build_record_is_deterministic_for_the_same_inputs():
    first = build_record(_task(), "step one", "s", _draft(), recorded_at=_AT)
    second = build_record(_task(), "step one", "s", _draft(), recorded_at=_AT)

    assert first == second


def test_the_criteria_body_carries_the_drafted_criterion():
    record = build_record(_task(), "step one", "s", _draft(), recorded_at=_AT)

    assert "returns 404 for an unknown id" in record.rendered[ChainArtifact.CRITERIA]


def test_record_chain_appends_to_the_stream(config):
    record_chain(config, _task(), "step one", "does a thing", None)

    lines = [
        line
        for line in config.change_chain_path.read_text().splitlines()
        if line.strip()
    ]
    assert json.loads(lines[-1])["issue_number"] == 7


def test_the_appended_stream_verifies_as_an_unbroken_chain(config):
    record_chain(config, _task(7), "step one", "s", None)
    record_chain(config, _task(8), "step two", "s", None)

    assert verify_file(config.change_chain_path).ok


def test_record_chain_returns_the_record_it_anchored(config):
    record = record_chain(config, _task(), "step one", "s", _draft())

    assert record is not None
    assert record.issue_number == 7


def test_record_chain_is_a_noop_when_the_kill_switch_is_off():
    config = ConfigFactory.create().model_copy(update={"change_chain_enabled": False})

    assert record_chain(config, _task(), "step one", "s", None) is None


def test_nothing_is_written_when_the_kill_switch_is_off():
    config = ConfigFactory.create().model_copy(update={"change_chain_enabled": False})

    record_chain(config, _task(), "step one", "s", None)

    assert not config.change_chain_path.exists()


def test_the_stream_carries_digests_only(config):
    """Bodies are scrubbed by AuditChain; a digest taken before would break."""
    record_chain(config, _task(), "step one", "does a thing", None)

    payload = json.loads(config.change_chain_path.read_text().splitlines()[-1])
    assert "rendered" not in payload


def test_the_bodies_land_in_the_local_cache(config):
    record_chain(config, _task(), "step one", "does a thing", None)

    cached = (config.chain_bodies_dir / "issue-7" / "plan.md").read_text(
        encoding="utf-8"
    )
    assert cached == render_plan(7, "step one", "does a thing")


def test_an_issue_body_with_a_credential_shaped_token_does_not_crash(config):
    """Arbitrary issue prose used to reach AuditChain's regex scrubber."""
    hostile = Task(
        id=7,
        title="Rotate a key",
        body='secret_key: AAAAAAAAAAAAAAAAAAAAAAAAA"quoted" and leaks.',
    )

    assert record_chain(config, hostile, "step one", "s", None) is not None


def test_an_audit_stream_defect_does_not_kill_the_planning_run(config, monkeypatch):
    """A broken append is a lost anchor, never a dead plan phase."""
    import change_chain_recorder

    class _Exploding:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def append(self, *_args, **_kwargs):
            raise ValueError("scrubber corrupted the payload")

    monkeypatch.setattr(change_chain_recorder, "AuditChain", _Exploding)

    assert record_chain(config, _task(), "step one", "s", None) is None
