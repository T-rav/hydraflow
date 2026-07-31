# tests/test_prompt_observatory.py
"""Observed prompt coverage: the denominator measured rather than inferred.

``test_prompt_registry_completeness`` asserts every *conventionally named*
Python builder is registered. It was verified on 2026-07-31 that a builder
called ``make_prompt`` and a Markdown template under ``prompts/`` both slip
past it with every gate green (#10857, #10858). This module tests the other
side: what the factory actually sent, recorded at the CH-6 gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import prompt_observatory
from prompt_observatory import (
    RESEMBLANCE_THRESHOLD,
    Observation,
    anchors,
    load_observations,
    observation_record,
    observe,
    reconcile,
    resemblance,
    reset_write_failures,
    shape_id,
    token_hashes,
    unrecognized_shapes,
    write_failures,
)

_PROMPT = """## Task
Review the diff and return a verdict.

**Issue**: #9812 retry S3 uploads
```diff
+    time.sleep(min(2 ** attempt, 8))
```
Respond with JSON only. If the diff is empty, return NO_CHANGES.
"""


class _Cfg:
    """Minimal stand-in; observe() only reads these three attributes."""

    def __init__(self, path: Path, *, enabled: bool = True) -> None:
        self.prompt_observatory_path = path
        self.prompt_observatory_enabled = enabled
        self.repo = "owner/repo"


def test_shape_is_stable_across_payload_changes() -> None:
    """One builder, different inputs, same shape — the whole premise.

    If the payload moved the shape, every run would look like a new prompt and
    the observed denominator would be noise.
    """
    a = _PROMPT
    b = _PROMPT.replace("#9812", "#9999").replace("retry S3 uploads", "fix flaky test")
    b = b.replace("2 ** attempt, 8", "3 ** attempt, 30")
    assert shape_id(a) == shape_id(b)


def test_shape_separates_different_prompts() -> None:
    other = "## Plan\nProduce an implementation plan.\n\n**Scope**: one module.\n"
    assert shape_id(_PROMPT) != shape_id(other)
    assert resemblance(anchors(_PROMPT), anchors(other)) < RESEMBLANCE_THRESHOLD


def test_record_carries_no_prompt_content() -> None:
    """Regulated-class prompts pass through here.

    Same rule as the gate's own audit stream: counts and digests, never
    content. A record that leaked a fragment would turn a measurement stream
    into a data-governance incident.
    """
    secret = (
        "## Patient record\n**Name**: Jane Doe, SSN 123-45-6789\n"
        "Contact jane.doe@hospital.example.com or key sk-live-AKIAIOSFODNN7\n"
        "Summarize the diagnosis and return a verdict on the treatment plan.\n"
    )
    blob = json.dumps(observation_record(secret, source="review", tool="claude"))
    for token in (
        "Jane",
        "Doe",
        "123-45-6789",
        "hospital",
        "sk-live",
        "AKIA",
        "diagnosis",
        "Patient",
    ):
        assert token.lower() not in blob.lower(), f"record leaked {token!r}"


def test_observe_writes_a_readable_record(tmp_path: Path) -> None:
    ledger = tmp_path / "observed.jsonl"
    observe(_PROMPT, config=_Cfg(ledger), source="review", tool="claude")
    loaded = load_observations(ledger)
    assert len(loaded) == 1
    obs = next(iter(loaded.values()))
    assert obs.source == "review"
    assert obs.tool == "claude"
    assert obs.tokens


def test_observe_is_disabled_by_the_kill_switch(tmp_path: Path) -> None:
    ledger = tmp_path / "observed.jsonl"
    observe(_PROMPT, config=_Cfg(ledger, enabled=False), source="review", tool="c")
    assert not ledger.exists()


def test_observe_never_raises(tmp_path: Path) -> None:
    """It sits on the hot path of every model call.

    A failure to *measure* a prompt must never stop the prompt being sent, so
    every foreseeable breakage is swallowed: unwritable path, absent config
    attributes, a config that raises on access.
    """

    class _Exploding:
        prompt_observatory_enabled = True

        @property
        def prompt_observatory_path(self):
            raise RuntimeError("disk gone")

    observe(_PROMPT, config=_Exploding(), source="s", tool="t")
    observe(_PROMPT, config=object(), source="s", tool="t")
    observe(
        _PROMPT, config=_Cfg(tmp_path / "no" / "such" / "dir.jsonl"), source="", tool=""
    )


def test_torn_trailing_write_does_not_lose_earlier_records(tmp_path: Path) -> None:
    """An append-only ledger can end mid-line if the process dies writing."""
    ledger = tmp_path / "observed.jsonl"
    observe(_PROMPT, config=_Cfg(ledger), source="review", tool="claude")
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write('{"shape": "s001-trunc", "sou')
    assert len(load_observations(ledger)) == 1


def test_unregistered_shape_is_detected() -> None:
    """The finding this whole module exists to produce."""
    registered = {"known": token_hashes(_PROMPT)}
    stranger = (
        "## Deployment runbook\n**Cluster**: prod-eu\n"
        "Roll the canary forward one step and confirm the error budget holds.\n"
        "Escalate to the on-call engineer when the budget is exhausted.\n"
    )
    obs = {
        "s-known": Observation("s-known", "triage", "claude", token_hashes(_PROMPT)),
        "s-new": Observation("s-new", "mystery", "claude", token_hashes(stranger)),
    }
    found = unrecognized_shapes(obs, registered)
    assert [f.shape for f in found] == ["s-new"], (
        "an observed prompt resembling nothing registered must be reported, and "
        "a registered one must not"
    )
    assert found[0].best_score < RESEMBLANCE_THRESHOLD


def test_thin_shapes_are_skipped_not_reported() -> None:
    """Unmatchable is not the same as unregistered.

    A prompt with almost no structure cannot be matched in either direction;
    reporting it would be noise dressed as a finding.
    """
    obs = {"s-thin": Observation("s-thin", "src", "tool", frozenset())}
    assert unrecognized_shapes(obs, {"known": token_hashes(_PROMPT)}) == []


@pytest.mark.parametrize("threshold", [0.0, RESEMBLANCE_THRESHOLD, 1.0])
def test_threshold_is_honoured(threshold: float) -> None:
    obs = {"s1": Observation("s1", "a", "b", token_hashes(_PROMPT))}
    registered = {"same": token_hashes(_PROMPT)}
    found = unrecognized_shapes(obs, registered, threshold=threshold)
    # Identical token sets resemble at 1.0, so only a threshold ABOVE that flags.
    assert bool(found) is (threshold > 1.0)


# --------------------------------------------------------------------------
# Trustworthiness. A measurement that dies quietly reports a clean bill of
# health it did not earn — the failure mode this subsystem exists to catch one
# level up, so it must not be the failure mode of the subsystem itself.
# --------------------------------------------------------------------------


def test_empty_ledger_is_untrustworthy_not_all_clear(tmp_path: Path) -> None:
    result = reconcile(tmp_path / "absent.jsonl")
    assert result.findings == []
    assert result.trustworthy is False, (
        "an absent ledger produces no findings; reading that as 'all clear' is "
        "how a dead observer passes for a healthy one"
    )
    assert "proves nothing" in result.summary


def test_write_failures_make_the_result_untrustworthy(tmp_path: Path) -> None:
    reset_write_failures()
    ledger = tmp_path / "observed.jsonl"
    observe(_PROMPT, config=_Cfg(ledger), source="review", tool="claude")

    class _Broken:
        prompt_observatory_enabled = True

        @property
        def prompt_observatory_path(self):
            raise RuntimeError("disk gone")

    observe(_PROMPT, config=_Broken(), source="review", tool="claude")
    assert write_failures() == 1

    result = reconcile(ledger, {"known": token_hashes(_PROMPT)})
    assert result.findings == []
    assert result.trustworthy is False
    assert "failed write" in result.summary
    reset_write_failures()


def test_healthy_reconciliation_reports_all_clear(tmp_path: Path) -> None:
    reset_write_failures()
    ledger = tmp_path / "observed.jsonl"
    observe(_PROMPT, config=_Cfg(ledger), source="review", tool="claude")
    result = reconcile(ledger, {"known": token_hashes(_PROMPT)})
    assert result.trustworthy is True
    assert result.findings == []
    assert "recognized" in result.summary


def test_acknowledged_shapes_are_the_verdict_not_the_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    """A finding is cleared by a written reason, not by moving a number."""
    reset_write_failures()
    ledger = tmp_path / "observed.jsonl"
    stranger = (
        "## Deployment runbook\n"
        "Roll the canary forward one step and confirm the error budget holds.\n"
        "Escalate to the on-call engineer when the budget is exhausted.\n"
    )
    observe(stranger, config=_Cfg(ledger), source="ops", tool="claude")
    registry = {"known": token_hashes(_PROMPT)}

    flagged = reconcile(ledger, registry)
    assert len(flagged.findings) == 1
    assert flagged.trustworthy is True

    monkeypatch.setitem(
        prompt_observatory.ACKNOWLEDGED_SHAPES,
        flagged.findings[0].shape,
        "operator runbook, not a model prompt",
    )
    cleared = reconcile(ledger, registry)
    assert cleared.findings == []
    assert cleared.trustworthy is True
    reset_write_failures()


def test_acknowledgements_are_pinned_and_justified() -> None:
    assert len(prompt_observatory.ACKNOWLEDGED_SHAPES) <= (
        prompt_observatory.ACKNOWLEDGED_SHAPES_MAX
    ), "acknowledgements grow only by decision; raise the pin deliberately"
    unexplained = sorted(
        s
        for s, why in prompt_observatory.ACKNOWLEDGED_SHAPES.items()
        if not why.strip()
    )
    assert not unexplained, f"acknowledged shapes with no reason: {unexplained}"
