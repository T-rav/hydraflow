"""Regression: unretired github cassettes carry ``baseline_only: true`` (Phase 4 of #8786).

The marker is the machine-checkable retirement signal — when a cassette is
covered by a live recorder (``record_github_mutation`` for mutating ops),
``baseline_only`` flips to ``false`` and the cassette becomes auto-refreshable.

This test guards against:
- New github cassettes landing without the marker when they should be baselines.
- A future PR accidentally flipping remaining baseline markers off in bulk.
- The schema field disappearing.

Cassettes promoted to live-recording via ``record_github_mutation`` (issue #8693)
are explicitly allowed to carry ``baseline_only: false``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from contracts._schema import Cassette

_GH_CASSETTES = Path(__file__).parent / "trust" / "contracts" / "cassettes" / "github"

# Cassettes covered by record_github_mutation — live-recorded, baseline_only: false.
_LIVE_RECORDED = frozenset({"close_issue.yaml", "create_issue.yaml", "merge_pr.yaml"})


def test_unretired_github_cassettes_are_baseline_only() -> None:
    """Every github cassette NOT in _LIVE_RECORDED must carry
    ``baseline_only: true``. Cassettes in _LIVE_RECORDED are auto-refreshed
    by ``record_github_mutation`` and are expected to carry ``baseline_only: false``."""
    yamls = list(_GH_CASSETTES.glob("*.yaml"))
    assert yamls, "expected at least one github cassette"
    missing: list[str] = []
    for path in yamls:
        if path.name in _LIVE_RECORDED:
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if raw.get("baseline_only") is not True:
            missing.append(path.name)
    assert not missing, (
        "the following github cassettes are missing `baseline_only: true`: "
        f"{missing}. See cassettes/github/README.md. If they are now live-recorded, "
        "add them to _LIVE_RECORDED in this test."
    )


def test_live_recorded_cassettes_have_baseline_only_false() -> None:
    """Cassettes managed by record_github_mutation must have baseline_only: false
    so ContractRefreshLoop can auto-regenerate them."""
    for name in sorted(_LIVE_RECORDED):
        path = _GH_CASSETTES / name
        assert path.exists(), f"expected live-recorded cassette at {path}"
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        assert raw.get("baseline_only") is not True, (
            f"{name}: live-recorded cassette must have baseline_only: false, "
            "not true — remove the baseline_only: true line or set it to false."
        )


def test_cassette_schema_round_trips_baseline_only() -> None:
    """The Cassette pydantic model preserves baseline_only on dump."""
    raw = {
        "adapter": "github",
        "interaction": "merge_pr",
        "recorded_at": "2026-05-13T00:00:00Z",
        "recorder_sha": "00000000",
        "fixture_repo": "x/y",
        "input": {"command": "merge_pr", "args": ["42"], "stdin": None, "env": {}},
        "output": {"exit_code": 0, "stdout": "", "stderr": ""},
        "normalizers": [],
        "baseline_only": True,
    }
    cassette = Cassette.model_validate(raw)
    assert cassette.baseline_only is True
    dumped = cassette.model_dump()
    assert dumped["baseline_only"] is True


def test_cassette_schema_defaults_baseline_only_false() -> None:
    """Default is False so existing live-recorded cassettes (git, docker,
    claude) don't suddenly claim to be baselines."""
    raw = {
        "adapter": "git",
        "interaction": "commit",
        "recorded_at": "2026-05-13T00:00:00Z",
        "recorder_sha": "abc1234",
        "fixture_repo": "x/y",
        "input": {"command": "commit", "args": ["initial"], "stdin": None, "env": {}},
        "output": {"exit_code": 0, "stdout": "[main abc1234] initial\n", "stderr": ""},
        "normalizers": ["sha:short"],
    }
    cassette = Cassette.model_validate(raw)
    assert cassette.baseline_only is False
