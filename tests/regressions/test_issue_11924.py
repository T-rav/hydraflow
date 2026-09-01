"""#11924 — the rail's staleness question must have exactly ONE answer.

Escape ``sampled-audit:11403:0bae96175dde``. The rail carries two independent
staleness signals and neither implies the other: ``pipelineSnapshotReady`` (the
server saying a snapshot is not authoritative yet, #11279) and
``pipelineSnapshotAt`` (the freshness stamp the reducer clears whenever it
empties the rail outside the snapshot path, #11414).

Two components derived the answer two different ways, so #11414 — which cleared
only the stamp — repaired ``OperatorConsole`` and left ``StreamView`` rendering
the same confidently-empty rail. A fixed defect shipped twice, one component
over, because the SHAPE was never addressed.

The behavioural pins live in ``src/ui/src/components/__tests__/``: the reset
paths are reducer transitions and the symptom is a render, so they belong in
the lane that runs the real reducer against the real component. What lives here
is the part that outlives this instance — the guards that stop a third consumer
inventing a fourth derivation.

The guarded set is DERIVED, never spelled. A hardcoded file list would pass
forever while a file added tomorrow read a raw signal, which is the same N-1
coverage that produced the escape.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_SRC = REPO_ROOT / "src" / "ui" / "src"

#: Raw staleness state. Only the reducer may write these, and only the
#: freshness util may interpret them; every other file asks ``railIsResyncing``.
_RAW_RAIL_SIGNALS = ("pipelineSnapshotReady", "pipelineSnapshotAt")

#: The two files allowed to name a raw signal, by role: the reducer that owns
#: the state, and the util that turns it into the one answer.
_SIGNAL_OWNERS = {
    Path("src") / "ui" / "src" / "context" / "HydraFlowContext.jsx",
    Path("src") / "ui" / "src" / "utils" / "pipelineFreshness.js",
}

#: The one derivation every consumer must route through.
_THE_ONE_ANSWER = "railIsResyncing"


def _ui_sources() -> list[Path]:
    return [
        path
        for pattern in ("*.js", "*.jsx")
        for path in UI_SRC.rglob(pattern)
        if "__tests__" not in path.parts and "node_modules" not in path.parts
    ]


def test_the_ui_tree_is_actually_being_scanned() -> None:
    """A guard over an empty file list passes silently and reads as coverage.

    Both checks below are membership tests over ``_ui_sources()``. If the path
    stopped resolving — a layout change, a moved directory — they would report
    a clean tree rather than an unread one, which is the failure mode the
    ``uncheckable-charter`` class exists to name.
    """
    sources = _ui_sources()

    assert len(sources) > 50, f"only {len(sources)} UI sources found under {UI_SRC}"


def test_no_component_derives_rail_staleness_from_a_raw_signal() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _ui_sources():
        relative = path.relative_to(REPO_ROOT)
        if relative in _SIGNAL_OWNERS:
            continue
        text = path.read_text(encoding="utf-8")
        named = [signal for signal in _RAW_RAIL_SIGNALS if signal in text]
        if named and _THE_ONE_ANSWER not in text:
            offenders[str(relative)] = named

    assert not offenders, (
        "these read the rail's raw staleness state without going through "
        f"{_THE_ONE_ANSWER}: {offenders}. The rail carries two independent "
        "signals and neither implies the other, so a component consulting one "
        "of them answers a different question than the rest of the console. "
        "That is exactly how the #11414 fix repaired OperatorConsole and left "
        "StreamView shipping the same confidently-empty rail (#11924). Ask "
        f"{_THE_ONE_ANSWER}, or extend it."
    )


def test_the_one_answer_still_reads_every_raw_signal() -> None:
    """Worthless guard above, if the util quietly stops consulting a signal.

    Dropping a term from ``railIsResyncing`` would make every consumer agree —
    on an answer that ignores a real staleness signal — while the membership
    check stayed green. The two guards fail on different mutations by design.
    """
    util = (UI_SRC / "utils" / "pipelineFreshness.js").read_text(encoding="utf-8")
    body = util[util.index(f"export function {_THE_ONE_ANSWER}") :]

    # The util destructures the signals, so it names them without the
    # `pipeline` prefix: `pipelineSnapshotAt` -> `snapshotAt`.
    missing = [
        signal
        for signal in _RAW_RAIL_SIGNALS
        if (lambda tail: tail[0].lower() + tail[1:])(signal.removeprefix("pipeline"))
        not in body
    ]

    assert not missing, (
        f"{_THE_ONE_ANSWER} no longer consults {missing}. Every consumer now "
        "agrees on an answer that ignores a real staleness signal."
    )
