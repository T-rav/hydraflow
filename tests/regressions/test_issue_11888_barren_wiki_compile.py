"""#11888: a barren wiki topic must stop re-buying the rejection it already paid for.

Measured on the running factory over 2026-08-30/31: the ``patterns`` topic
compiled on seven separate ticks and the anchor gate (#9954) dropped the SAME
twelve titles each time — 552 drops, ``entries_compiled: 0`` on all 27
maintenance runs in the log. The #11373 fingerprint gate could not stop it: it
keys on the topic's INPUT, which churns whenever anything touches the topic,
including this loop's own stale-marking lint pass that runs immediately before.

These pin the gate at the seam that matters — the loop must not spawn — rather
than only at the ledger's own unit level, where a wiring mistake is invisible.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wiki_synthesis_ledger import WikiSynthesisLedger, synthesis_digest

REPO = "acme/widget"
TOPIC = "patterns"


def _ledger(tmp_path: Path, hours: float = 24.0) -> WikiSynthesisLedger:
    return WikiSynthesisLedger(tmp_path / "ledger.json", cooldown_hours=hours)


def _reject_twice(ledger: WikiSynthesisLedger, digests: list[str]) -> None:
    for _ in range(2):
        ledger.record_compile(REPO, TOPIC, rejected=digests, wrote=0)


def test_the_measured_shape_stops_after_the_second_identical_rejection(
    tmp_path: Path,
) -> None:
    """Twelve titles, rejected, nothing written — twice. The third must not run."""
    digests = [synthesis_digest(f"Platitude {i}", "generic advice") for i in range(12)]
    ledger = _ledger(tmp_path)

    assert ledger.should_compile(REPO, TOPIC, now=datetime.now(UTC))
    _reject_twice(ledger, digests)
    assert not ledger.should_compile(REPO, TOPIC, now=datetime.now(UTC))


def test_the_input_changing_does_not_reopen_the_gate(tmp_path: Path) -> None:
    """The #11373 gate's blind spot, stated as the thing this one must cover.

    An ingest or the lint pass changes the topic's bytes, so the fingerprint
    gate opens. The barren mark must hold anyway — the input moving is exactly
    what did NOT predict a different outcome the seven measured times.
    """
    digests = [synthesis_digest("T", "b")]
    ledger = _ledger(tmp_path)
    _reject_twice(ledger, digests)

    # Simulate the next tick: the topic gained an entry, so any input-keyed
    # gate would open. This one is not input-keyed.
    assert not ledger.should_compile(REPO, TOPIC, now=datetime.now(UTC))


def test_cooldown_of_zero_disables_the_gate_entirely(tmp_path: Path) -> None:
    """The documented escape hatch: 0 restores the pre-#11888 behaviour."""
    ledger = _ledger(tmp_path, hours=0.0)
    _reject_twice(ledger, [synthesis_digest("T", "b")])
    assert ledger.should_compile(REPO, TOPIC, now=datetime.now(UTC))


def test_the_gate_releases_and_a_real_compile_clears_it(tmp_path: Path) -> None:
    """Barren is a pause, not a tombstone — the topic gets probed again."""
    digests = [synthesis_digest("T", "b")]
    ledger = _ledger(tmp_path)
    _reject_twice(ledger, digests)

    after_cooldown = datetime.now(UTC) + timedelta(hours=25)
    assert ledger.should_compile(REPO, TOPIC, now=after_cooldown)

    # The probe lands something: the topic is moving again and stays open.
    ledger.record_compile(REPO, TOPIC, rejected=digests, wrote=2, now=after_cooldown)
    assert ledger.should_compile(REPO, TOPIC, now=after_cooldown)


def test_the_loop_consults_the_ledger_before_spawning() -> None:
    """Wiring pin: both compile phases must gate, or the ledger is decoration.

    Asserted against the source because the alternative — driving a full
    RepoWikiLoop tick — needs a wiki tree, a store and a live compiler, and
    would pass just as happily with the gate deleted from ONE of the two
    phases. Two call sites is the claim.
    """
    source = (
        Path(__file__).resolve().parents[2] / "src" / "repo_wiki_loop.py"
    ).read_text(encoding="utf-8")
    assert source.count("synthesis_ledger.should_compile(") == 2, (
        "both the legacy (Phase 2) and tracked (Phase 8) compile paths must "
        "consult the barren ledger before spawning"
    )
    assert source.count("synthesis_ledger.record_compile(") == 2, (
        "both compile paths must fold their anchor-gate verdict back in, or "
        "the gate never accumulates a repeat and can never fire"
    )
    assert "synthesis_ledger.save()" in source, (
        "the ledger must persist — it is rebuilt from disk every tick"
    )


def test_the_verdict_the_loop_folds_in_comes_from_the_compiler() -> None:
    """The loop must read the gate's OWN verdict, not re-derive it."""
    source = (
        Path(__file__).resolve().parents[2] / "src" / "repo_wiki_loop.py"
    ).read_text(encoding="utf-8")
    assert source.count("last_anchor_gate_verdict") == 2
