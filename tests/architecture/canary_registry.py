"""The canary family: one rule, three phases, and where each phase states it.

#11716. ``plan_broker``, ``implement_broker`` and ``review_broker`` each expose
a ``*_canary_covers`` predicate, and ``HydraFlowConfig`` exposes a matching
``fable_*_canary_armed`` badge. That is **one rule written in six places**, and
two of its clauses went unpinned in almost all of them:

- the off-switch (``if armed is None: return False``) — deleting it survived
  the full suite in 5 of 6 places;
- clause 2's canonicalisation — dropping ``canonicalize_repo`` on the
  ``config.repo`` operand survived in **all six**, so ``repo="Acme/Widget"``
  against a dial typed ``acme/widget`` made an armed canary cover nothing.

#11714 pinned both, by hand, six times. This registry is what stops the fourth
canary needing a seventh copy: the conformance properties in
``test_canary_family_conformance.py`` run over whatever this returns, and
``test_guard_enumeration_gate.py`` holds the registry to the set of brokers
that actually export the predicate — so a new canary either joins the sweep or
reddens.

Every callable here is resolved from the live module. A re-implementation of a
clause would be a seventh copy inside the thing built to stop the seventh copy
(``docs/standards/parametrised_guards/README.md``).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from config import HydraFlowConfig
    from driver_contracts import DriverPhase

__all__ = [
    "Canary",
    "discovered_canaries",
    "registered_canaries",
    "repo_root",
]

#: The suffix that makes a broker function the canary's bound predicate.
COVERS_SUFFIX = "_canary_covers"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Canary:
    """One phase's canary, and every surface that states its rule."""

    name: str
    """The phase's lowercase name — ``plan``, ``implement``, ``review``. Also
    the key the derivation produces from ``src/<name>_broker.py``."""

    module: str
    """Repo-relative path of the broker that owns the bound."""

    dial: str
    """The ``HydraFlowConfig`` field an operator sets. The one-action switch."""

    phase: DriverPhase
    """Read from the broker's own ``CANARY_PHASE``, never re-typed here."""

    covers: Callable[..., bool]
    """The live ``<name>_canary_covers`` — the bound."""

    armed: Callable[[HydraFlowConfig], bool]
    """The live ``<name>_canary_armed`` — the broker's off-switch reading."""

    badge: Callable[[HydraFlowConfig], bool]
    """The live ``HydraFlowConfig.fable_<name>_canary_armed`` — the operator's
    badge, which asks the same question over an additional decision (whether
    the Fable director is selected at all)."""


def _canary_for(name: str) -> Canary:
    """Resolve one phase's canary from the live modules.

    Every field is read off the module or the config class, so a phase whose
    predicate, badge or ``CANARY_PHASE`` is missing raises here rather than
    being quietly absent from the sweep. Resolution HAPPENS — the sibling
    failure this repo has already shipped once is a gate that asserts a
    literal is *present* and is vacuously satisfiable.
    """
    import importlib

    from config import HydraFlowConfig

    module = importlib.import_module(f"{name}_broker")
    badge = getattr(HydraFlowConfig, f"fable_{name}_canary_armed")
    return Canary(
        name=name,
        module=f"src/{name}_broker.py",
        dial=f"fable_{name}_canary_repo",
        phase=module.CANARY_PHASE,
        covers=getattr(module, f"{name}{COVERS_SUFFIX}"),
        armed=getattr(module, f"{name}_canary_armed"),
        badge=lambda config: bool(badge(config)),
    )


#: The literal enumeration of canaries under the family sweep.
#:
#: Hand-maintained ON PURPOSE, and pinned against :func:`discovered_canaries`
#: in both directions by ``test_guard_enumeration_gate.py``. A registry that
#: merely returned the derivation would make that equality tautological — the
#: exact "assert the thing against itself" shape
#: ``docs/standards/parametrised_guards`` is about. Two independently produced
#: sets that must agree is the only arrangement where dropping a member
#: reddens.
REGISTERED_PHASES: tuple[str, ...] = ("plan", "implement", "review")


def registered_canaries() -> tuple[Canary, ...]:
    """Every canary under the family conformance sweep, fully resolved."""
    return tuple(_canary_for(name) for name in REGISTERED_PHASES)


def discovered_canaries() -> tuple[Canary, ...]:
    """Every broker in ``src`` that exports a ``*_canary_covers`` predicate.

    The derivation, produced independently of :data:`REGISTERED_PHASES` by
    reading what is on disk. A fourth canary appears here the moment its
    broker does, so joining the sweep is the cheap path and staying out of it
    reddens.
    """
    found: list[Canary] = []
    for path in sorted((repo_root() / "src").glob("*_broker.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not (
                isinstance(node, ast.FunctionDef) and node.name.endswith(COVERS_SUFFIX)
            ):
                continue
            found.append(_canary_for(node.name[: -len(COVERS_SUFFIX)]))
    return tuple(found)
