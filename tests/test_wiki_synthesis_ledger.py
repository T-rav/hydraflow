"""Unit tests for the barren-compile ledger (#11888).

The #11373 fingerprint gate keys on a topic's INPUT content. That content
churns for reasons unrelated to whether synthesis can make progress — an
ingest, a stale-marking lint pass, a landed maintenance PR — so the gate
re-opens and the loop re-pays a full synthesis spawn. Measured live over
2026-08-30/31: ``patterns`` compiled on seven separate ticks and the anchor
gate dropped the SAME twelve titles each time; 552 drops, 0 entries written.

This ledger remembers the OUTPUT instead. A compile that writes nothing and
whose every rejection was already known bought nothing, and the topic is
marked barren until a cooldown elapses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from wiki_synthesis_ledger import WikiSynthesisLedger, synthesis_digest


def _ledger(tmp_path: Path) -> WikiSynthesisLedger:
    return WikiSynthesisLedger(tmp_path / "ledger.json", cooldown_hours=24)


def test_digest_is_stable_across_whitespace_and_case() -> None:
    """The model re-emits the same claim with cosmetic drift; that is one rejection."""
    a = synthesis_digest("Use is None for sentinels", "Prefer  `is None`.\n")
    b = synthesis_digest("use IS NONE for sentinels", "Prefer `is None`.")
    assert a == b


def test_digest_separates_distinct_claims() -> None:
    assert synthesis_digest("A", "body") != synthesis_digest("B", "body")


def test_first_rejection_is_new_so_the_topic_is_not_barren(tmp_path: Path) -> None:
    """A rejection nobody has seen is progress of a kind — the topic still moves."""
    ledger = _ledger(tmp_path)
    barren = ledger.record_compile(
        "acme/widget", "patterns", rejected=[synthesis_digest("T", "b")], wrote=0
    )
    assert barren is False
    assert ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))


def test_repeating_a_known_rejection_with_no_writes_marks_barren(
    tmp_path: Path,
) -> None:
    """The measured failure: same rejection, nothing written, second time around."""
    ledger = _ledger(tmp_path)
    digest = synthesis_digest("T", "b")
    ledger.record_compile("acme/widget", "patterns", rejected=[digest], wrote=0)
    barren = ledger.record_compile(
        "acme/widget", "patterns", rejected=[digest], wrote=0
    )
    assert barren is True
    assert not ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))


def test_barren_topic_recompiles_once_the_cooldown_elapses(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    digest = synthesis_digest("T", "b")
    ledger.record_compile("acme/widget", "patterns", rejected=[digest], wrote=0)
    ledger.record_compile("acme/widget", "patterns", rejected=[digest], wrote=0)
    later = datetime.now(UTC) + timedelta(hours=25)
    assert ledger.should_compile("acme/widget", "patterns", now=later)


def test_a_write_clears_barren_even_with_known_rejections(tmp_path: Path) -> None:
    """Partial progress is progress: some entries landed, so keep compiling."""
    ledger = _ledger(tmp_path)
    digest = synthesis_digest("T", "b")
    ledger.record_compile("acme/widget", "patterns", rejected=[digest], wrote=0)
    ledger.record_compile("acme/widget", "patterns", rejected=[digest], wrote=0)
    assert not ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))
    ledger.record_compile("acme/widget", "patterns", rejected=[digest], wrote=3)
    assert ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))


def test_a_new_rejection_clears_barren(tmp_path: Path) -> None:
    """A rejection never seen before means the output changed — it is still moving."""
    ledger = _ledger(tmp_path)
    old = synthesis_digest("T", "b")
    ledger.record_compile("acme/widget", "patterns", rejected=[old], wrote=0)
    ledger.record_compile("acme/widget", "patterns", rejected=[old], wrote=0)
    assert not ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))
    ledger.record_compile(
        "acme/widget", "patterns", rejected=[old, synthesis_digest("N", "b")], wrote=0
    )
    assert ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))


def test_a_compile_that_rejects_nothing_never_marks_barren(tmp_path: Path) -> None:
    """Zero output is the timeout/None path — that is the breaker's job, not this."""
    ledger = _ledger(tmp_path)
    ledger.record_compile("acme/widget", "patterns", rejected=[], wrote=0)
    assert (
        ledger.record_compile("acme/widget", "patterns", rejected=[], wrote=0) is False
    )
    assert ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))


def test_topics_are_independent(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    digest = synthesis_digest("T", "b")
    for _ in range(2):
        ledger.record_compile("acme/widget", "patterns", rejected=[digest], wrote=0)
    assert not ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))
    assert ledger.should_compile("acme/widget", "testing", now=datetime.now(UTC))
    assert ledger.should_compile("other/repo", "patterns", now=datetime.now(UTC))


def test_state_survives_a_reload(tmp_path: Path) -> None:
    """The loop builds a fresh ledger every tick; barren must outlive the process."""
    path = tmp_path / "ledger.json"
    first = WikiSynthesisLedger(path, cooldown_hours=24)
    digest = synthesis_digest("T", "b")
    for _ in range(2):
        first.record_compile("acme/widget", "patterns", rejected=[digest], wrote=0)
    first.save()

    second = WikiSynthesisLedger(path, cooldown_hours=24)
    assert not second.should_compile("acme/widget", "patterns", now=datetime.now(UTC))


def test_corrupt_state_fails_open(tmp_path: Path) -> None:
    """A gate that can only ever SAVE spawns, never suppress a real one (#11373)."""
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    ledger = WikiSynthesisLedger(path, cooldown_hours=24)
    assert ledger.should_compile("acme/widget", "patterns", now=datetime.now(UTC))


def test_idle_tick_does_not_touch_disk(tmp_path: Path) -> None:
    """The wiki heal contract asserts a byte-clean tree on an idle tick."""
    path = tmp_path / "ledger.json"
    WikiSynthesisLedger(path, cooldown_hours=24).save()
    assert not path.exists()
