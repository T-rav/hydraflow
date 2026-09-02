"""Which principals each provider dial governs, swept from the tree (#11991).

P6b turns each legacy `*_provider` dial into a generated baseline policy.
`RoutingMatch` joins on `principal_ids` and `run_lightweight_agent` passes
`principal_id=source`, so a generated policy needs the set of `source` strings
its dial governs.

**The obvious derivation does not work, and this file exists because it was
tested rather than assumed.** The loop key in `_BACKEND_WORKER_LOOPS` is not
the source: `triage.py` carries `source="triage_honeypot"`, which belongs to a
different dial, and `planner.py` passes no literal source at all. A generator
built on that join would match the wrong principals — and the mis-route is
silent, because every spawn still succeeds against *some* provider.

So the map is swept from the tree: a call passing both `provider=config.X` and
a literal `source=` pairs them. What that cannot see is registered below, by
site, so the gap is a list rather than a surprise.

`adr_review_provider` governs two principals. The relationship is one-to-many,
which a policy per dial has to carry as a set.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"


def _dial_of(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr.endswith("_provider"):
        return node.attr
    return None


def _sweep() -> tuple[dict[str, set[str]], tuple[tuple[str, int, str], ...]]:
    """(dial -> literal sources, sites naming a dial with no literal source)."""
    paired: dict[str, set[str]] = collections.defaultdict(set)
    unpaired: list[tuple[str, int, str]] = []
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            kw = {k.arg: k.value for k in call.keywords if k.arg}
            dial = _dial_of(kw["provider"]) if "provider" in kw else None
            if not dial:
                continue
            source = kw.get("source")
            if isinstance(source, ast.Constant) and isinstance(source.value, str):
                paired[dial].add(source.value)
            else:
                unpaired.append(
                    (path.relative_to(_SRC.parent).as_posix(), call.lineno, dial)
                )
    return dict(paired), tuple(unpaired)


DIAL_SOURCES, UNRESOLVED_SITES = _sweep()

#: Spawn sites that name a dial but take their `source` from context rather
#: than a literal, so the sweep cannot pair them. Each needs tracing before
#: P6b can emit a policy for that dial.
#:
#: Keyed on `file::dial`, NOT on a line number. The first version keyed on
#: `path:line` and broke the moment it ran against a branch where the file had
#: shifted — caught by this file's own staleness test, which is the failure it
#: warns about happening to it. A note may name several principals when one
#: file spawns on one dial from more than one place.
_SOURCE_FROM_CONTEXT: dict[str, str] = {
    "src/acceptance_criteria.py::ac_provider": (
        "ac_generator, ac_precheck, ac_precheck_debug — each passed through "
        "event_data['source'] rather than the call"
    ),
    "src/service_registry.py::planner_provider": "source threaded by the runner",
    "src/service_registry.py::term_proposer_provider": (
        "source threaded by the runner"
    ),
    "src/term_proposer_runtime.py::_provider": (
        "provider is a parameter here, not a config read; the caller owns both"
    ),
    "src/triage_honeypot.py::triage_honeypot_provider": (
        "source threaded by the runner"
    ),
    "src/verification_judge.py::review_provider": (
        "the verification judge shares review's tool+model, so it shares its "
        "dial; its principal is the judge, not the reviewer"
    ),
}


def test_the_sweep_found_the_pairs_it_was_built_from() -> None:
    """Anti-vacuity: an empty sweep would make every assertion below pass."""
    assert DIAL_SOURCES, "the sweep paired no dial with any source"
    assert "adr_review_provider" in DIAL_SOURCES


def test_a_dial_can_govern_more_than_one_principal() -> None:
    """One-to-many, so a generated policy carries a SET of principal_ids.

    Pinned because a policy generator that assumed one source per dial would
    silently drop `decomposition_ensemble` and route it on the default.
    """
    assert DIAL_SOURCES["adr_review_provider"] >= {
        "adr_reviewer",
        "decomposition_ensemble",
    }


_UNRESOLVED_KEYS = tuple(sorted({f"{p}::{d}" for p, _n, d in UNRESOLVED_SITES}))


@pytest.mark.parametrize("key", _UNRESOLVED_KEYS, ids=_UNRESOLVED_KEYS)
def test_an_unpaired_spawn_site_is_registered(key: str) -> None:
    """A new spawn site must declare where its principal comes from.

    Left unregistered, P6b would emit a policy for `dial` whose principal set
    is missing this site — and the spawn would fall through to the default
    while every test stayed green.
    """
    note = _SOURCE_FROM_CONTEXT.get(key)

    assert note, (
        f"{key} spawns without a literal source and is not registered. Record "
        f"where its principal comes from, so #11991's generator knows this "
        f"dial governs it."
    )


def test_no_registration_is_stale() -> None:
    """A site that gained a literal source must lose its row, not keep it."""
    live = set(_UNRESOLVED_KEYS)
    stale = sorted(set(_SOURCE_FROM_CONTEXT) - live)

    assert not stale, (
        f"these sites are registered as context-sourced but the sweep no "
        f"longer finds them: {stale}. Drop the row, or re-run the sweep if the "
        f"site moved to another file."
    )
