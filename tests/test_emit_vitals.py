"""The vitals emitter: self-identifying, discovered by shape, and small."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from emit_vitals import (  # noqa: E402
    SCHEMA_VERSION,
    baseline_metrics,
    emit,
    main,
    repo_identity,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(dirpath: Path, name: str, payload: object) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / name).write_text(yaml.safe_dump(payload))


def test_a_new_baseline_file_is_emitted_without_editing_the_emitter(
    tmp_path: Path,
) -> None:
    """Discovery by glob. A hardcoded roster stops seeing a new baseline and
    reports a smaller, healthy-looking document with nothing red (#11673)."""
    _write(tmp_path, "invented_tomorrow.yaml", {"comment": "prose", "widgets": 7})
    metrics = baseline_metrics(tmp_path)
    assert metrics["invented_tomorrow"] == {"widgets": 7.0}


def test_prose_is_not_a_measurement(tmp_path: Path) -> None:
    _write(tmp_path, "b.yaml", {"comment": "why this moved", "n": 3})
    assert baseline_metrics(tmp_path)["b"] == {"n": 3.0}


def test_a_flag_is_not_a_measurement(tmp_path: Path) -> None:
    """``isinstance(True, int)`` is True in Python, so this needs saying."""
    _write(tmp_path, "b.yaml", {"enabled": True, "n": 2})
    assert baseline_metrics(tmp_path)["b"] == {"n": 2.0}


def test_a_collection_of_records_summarises_per_field(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mass.yaml",
        {"classes": {"a": {"loc": 10, "methods": 2}, "b": {"loc": 30, "methods": 4}}},
    )
    assert baseline_metrics(tmp_path)["mass"] == {
        "classes.count": 2.0,
        "classes.loc.total": 40.0,
        "classes.loc.max": 30.0,
        "classes.methods.total": 6.0,
        "classes.methods.max": 4.0,
    }


def test_a_collection_of_bare_numbers_summarises_on_the_value(tmp_path: Path) -> None:
    """``suppressions``/``traceability`` shape: the value IS the field."""
    _write(tmp_path, "suppressions.yaml", {"entries": {"x::noqa": 3, "y::noqa": 5}})
    assert baseline_metrics(tmp_path)["suppressions"] == {
        "entries.count": 2.0,
        "entries.total": 8.0,
        "entries.max": 5.0,
    }


def test_an_empty_collection_reports_a_count_not_nothing(tmp_path: Path) -> None:
    """An absent metric reads as a healthy zero; an explicit zero does not."""
    _write(tmp_path, "b.yaml", {"entries": {}})
    assert baseline_metrics(tmp_path)["b"] == {"entries.count": 0.0}


def test_an_unparseable_baseline_is_reported_not_skipped(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "broken.yaml").write_text("{ this: is: not: yaml")
    assert baseline_metrics(tmp_path)["broken"] == {"_unparseable": 1.0}


def test_the_document_identifies_which_factory_and_which_tree() -> None:
    """Identity is the load-bearing part. Two hosts both reporting 451 are the
    same fact or two different facts depending entirely on this block."""
    identity = repo_identity()
    assert set(identity) == {"repo", "branch", "head_sha", "dirty", "host"}
    assert identity["head_sha"], "no commit — the numbers describe nothing"
    assert identity["host"]
    assert isinstance(identity["dirty"], bool)


def test_a_dirty_tree_is_reported_not_suppressed() -> None:
    """A reading from a tree with uncommitted changes is not a reading of
    head_sha; an aggregate that mixes them compares a commit to a working copy."""
    assert "dirty" in repo_identity()


def test_the_document_is_stamped_and_versioned() -> None:
    doc = emit(now=datetime(2026, 8, 24, tzinfo=UTC))
    assert doc["kind"] == "hydraflow.vitals"
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["emitted_at"] == "2026-08-24T00:00:00+00:00"


def test_the_document_stays_small_enough_to_compare_across_hosts() -> None:
    """Emitting every leaf produced ~700 keys from suppressions alone."""
    payload = json.dumps(emit())
    assert len(payload) < 8000, (
        f"vitals document is {len(payload)} bytes — too granular to aggregate. "
        "Summarise by shape rather than emitting every leaf."
    )


def test_it_carries_no_conformance_claim() -> None:
    """A VITALS emitter (#11688). Nothing here asserts a gate holds — a claim
    auditable only through a data plane's uptime is not a claim."""
    doc = emit()
    flat = json.dumps(doc).lower()
    for word in ("passed", "conformant", "verdict", "approved", "holds"):
        assert word not in flat, f"{word!r} reads as a conformance claim"


def test_the_cli_emits_parseable_json_on_stdout() -> None:
    out = subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "emit_vitals.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    doc = json.loads(out.stdout)
    assert doc["kind"] == "hydraflow.vitals"


def test_pretty_is_the_same_document(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--pretty"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "hydraflow.vitals"


def test_the_real_repo_emits_every_committed_baseline() -> None:
    """Guards the glob against pointing somewhere empty."""
    on_disk = {
        p.stem for p in (_REPO_ROOT / "disturbance" / "baselines").glob("*.yaml")
    }
    assert on_disk, "no baselines found — discovery is looking in the wrong place"
    assert set(baseline_metrics()) == on_disk
