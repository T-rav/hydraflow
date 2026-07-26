"""Integrity gate: fail when an extractor emits a degenerate generated artifact.

Motivation (issue #10622). Several generated architecture pages once conveyed
false/empty information while their paired drift tests stayed green:

* the events topology flagged **every** event ⚠️ "likely dead" because the
  extractor modeled a per-``EventType`` ``subscribe(EventType.X, ...)`` API the
  fan-out ``EventBus`` never exposed (#10619/#10629 — 0 fan-out subscribers);
* the label state machine rendered ``_(no transitions discovered)_`` because
  there was no canonical transition table to read (#10621 — 0 transitions);
* near-misses lurked elsewhere.

The shared failure mode: an extractor pattern-matches a code shape the codebase
does not use, emits an empty/degenerate artifact, and the lenient paired test
passes on emptiness. This module makes **emptiness an alarm, not a silently
passing state**.

Each extractor declares a *minimum-signal invariant* — e.g. "this repo has >=1
fan-out event consumer", ">=1 label transition", ">=1 ADR->module citation
edge". :func:`run_integrity_checks` runs the real (pure, AST-based) extractors
over ``src/`` (plus the ADR / fakes / scenario trees) and reports every
artifact whose signal fell below its declared floor. Emptiness is tolerated
only where an invariant sets ``expected_empty=True`` (none today) — that is the
explicit "this artifact is allowed to be empty" escape hatch the issue calls
for.

Pure and deterministic: it only calls the extractors (themselves pure); it
never imports application modules or runs side effects.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from arch.extractors.adr_xref import extract_adr_refs
from arch.extractors.events import extract_event_topology
from arch.extractors.labels import extract_labels
from arch.extractors.loops import extract_loops
from arch.extractors.mockworld import extract_mockworld_map
from arch.extractors.modules import extract_module_graph
from arch.extractors.ports import extract_ports


@dataclass(frozen=True)
class IntegrityInvariant:
    """A minimum-signal floor an extractor's artifact must clear.

    ``signal`` names a key produced by the artifact's probe (see ``_PROBES``);
    the artifact is degenerate when that count is below ``minimum``. Set
    ``expected_empty=True`` to explicitly declare emptiness acceptable — the
    only sanctioned way to silence the alarm.
    """

    artifact: str  # generated filename, e.g. "events.md"
    signal: str  # signal label, must match a key in the artifact's probe
    minimum: int = 1
    expected_empty: bool = False
    reason: str = ""


@dataclass(frozen=True)
class IntegrityViolation:
    """A degenerate artifact: an observed signal below its declared floor."""

    artifact: str
    signal: str
    observed: int
    minimum: int
    reason: str

    def __str__(self) -> str:
        return (
            f"{self.artifact}: degenerate — observed {self.observed} "
            f"{self.signal} (expected >= {self.minimum}). {self.reason}"
        )


# --------------------------------------------------------------------------
# Probes — one per extractor. Each runs the real extractor over the repo and
# returns {signal_label: count}. A missing directory degrades to empty output
# (the extractors already tolerate that), which yields 0 counts and therefore a
# violation — fail-closed, which is the intended behavior.
# --------------------------------------------------------------------------


def probe_events(repo_root: Path) -> dict[str, int]:
    topo = extract_event_topology(Path(repo_root) / "src")
    return {
        "publisher edges": sum(len(e.publishers) for e in topo.events),
        "fan-out subscribers": len(topo.global_subscribers),
    }


def probe_labels(repo_root: Path) -> dict[str, int]:
    sm = extract_labels(Path(repo_root) / "src")
    return {"transitions": len(sm.transitions), "states": len(sm.states)}


def probe_adr_xref(repo_root: Path) -> dict[str, int]:
    idx = extract_adr_refs(Path(repo_root) / "docs" / "adr")
    edges = sum(len(ref.cited_modules) for ref in idx.adr_to_modules)
    return {"ADR->module citation edges": edges}


def probe_loops(repo_root: Path) -> dict[str, int]:
    return {"loops": len(extract_loops(Path(repo_root) / "src"))}


def probe_ports(repo_root: Path) -> dict[str, int]:
    root = Path(repo_root)
    ports = extract_ports(
        src_dir=root / "src", fakes_dir=root / "src" / "mockworld" / "fakes"
    )
    return {"ports": len(ports)}


def probe_modules(repo_root: Path) -> dict[str, int]:
    graph = extract_module_graph(Path(repo_root) / "src")
    return {"module nodes": len(graph.nodes), "module import edges": len(graph.edges)}


def probe_mockworld(repo_root: Path) -> dict[str, int]:
    root = Path(repo_root)
    mw = extract_mockworld_map(
        fakes_dir=root / "src" / "mockworld" / "fakes",
        scenarios_dir=root / "tests" / "scenarios",
    )
    return {"fakes": len(mw.fakes)}


_PROBES: dict[str, Callable[[Path], dict[str, int]]] = {
    "events.md": probe_events,
    "labels.md": probe_labels,
    "adr_xref.md": probe_adr_xref,
    "loops.md": probe_loops,
    "ports.md": probe_ports,
    "modules.md": probe_modules,
    "mockworld.md": probe_mockworld,
}


# --------------------------------------------------------------------------
# Declared invariants — one or more per extractor. Every floor is 1 (a healthy
# repo is comfortably above these; see tests/architecture/test_arch_integrity.py
# for the observed real-repo counts). ``expected_empty`` is False everywhere:
# no HydraFlow artifact is legitimately empty today.
# --------------------------------------------------------------------------

INVARIANTS: tuple[IntegrityInvariant, ...] = (
    IntegrityInvariant(
        artifact="events.md",
        signal="publisher edges",
        reason=(
            "At least one EventType must be published from src/. Zero means the "
            "publish(EventType.X) scan matched nothing and the events topology "
            "is empty/false."
        ),
    ),
    IntegrityInvariant(
        artifact="events.md",
        signal="fan-out subscribers",
        reason=(
            "HydraFlow's fan-out EventBus has >=1 real consumer (the dashboard "
            "WebSocket). Zero means the extractor stopped recognizing argless "
            "subscribe()/subscription() — the #10619/#10629 regression where "
            "every event was falsely flagged 'likely dead'."
        ),
    ),
    IntegrityInvariant(
        artifact="labels.md",
        signal="transitions",
        reason=(
            "The pipeline label state machine declares >=1 transition "
            "(label_transitions.LABEL_TRANSITIONS). Zero means the canonical "
            "table was lost and labels.md renders '_(no transitions "
            "discovered)_' — the #10621 regression."
        ),
    ),
    IntegrityInvariant(
        artifact="adr_xref.md",
        signal="ADR->module citation edges",
        reason=(
            "At least one ADR cites a src/ module. Zero means the ADR "
            "path-reference scan matched nothing and the cross-reference is "
            "empty."
        ),
    ),
    IntegrityInvariant(
        artifact="loops.md",
        signal="loops",
        reason=(
            "At least one BaseBackgroundLoop subclass exists. Zero means the "
            "loop-registry extractor found no loops."
        ),
    ),
    IntegrityInvariant(
        artifact="ports.md",
        signal="ports",
        reason=(
            "At least one typing.Protocol Port exists. Zero means the port-map "
            "extractor found no Ports."
        ),
    ),
    IntegrityInvariant(
        artifact="modules.md",
        signal="module import edges",
        reason=(
            "The src/ package import graph has >=1 internal edge. Zero means the "
            "module graph collapsed to isolated nodes."
        ),
    ),
    IntegrityInvariant(
        artifact="mockworld.md",
        signal="fakes",
        reason=(
            "At least one Fake adapter is registered. Zero means the MockWorld "
            "map is empty."
        ),
    ),
)


def _violation_for(
    inv: IntegrityInvariant, counts: Mapping[str, int]
) -> IntegrityViolation | None:
    if inv.expected_empty:
        return None
    observed = counts.get(inv.signal, 0)
    if observed < inv.minimum:
        return IntegrityViolation(
            artifact=inv.artifact,
            signal=inv.signal,
            observed=observed,
            minimum=inv.minimum,
            reason=inv.reason,
        )
    return None


def evaluate_artifact(
    artifact: str, counts: Mapping[str, int]
) -> list[IntegrityViolation]:
    """Apply just this artifact's invariants to its probed signal counts."""
    out: list[IntegrityViolation] = []
    for inv in INVARIANTS:
        if inv.artifact != artifact:
            continue
        violation = _violation_for(inv, counts)
        if violation is not None:
            out.append(violation)
    return out


def evaluate(
    counts_by_artifact: Mapping[str, Mapping[str, int]],
) -> list[IntegrityViolation]:
    """Apply every declared invariant to a per-artifact probe result."""
    out: list[IntegrityViolation] = []
    for inv in INVARIANTS:
        violation = _violation_for(inv, counts_by_artifact.get(inv.artifact, {}))
        if violation is not None:
            out.append(violation)
    return out


def probe_repo(repo_root: Path) -> dict[str, dict[str, int]]:
    """Run every extractor over the real repo; return {artifact: {signal: n}}."""
    root = Path(repo_root).resolve()
    return {artifact: probe(root) for artifact, probe in _PROBES.items()}


def run_integrity_checks(repo_root: Path) -> list[IntegrityViolation]:
    """The gate: return every degenerate-artifact violation (empty == healthy)."""
    return evaluate(probe_repo(repo_root))
