"""Every one-shot spawn face is governed, or is registered with a reason (#11544).

``test_governed_spawn_seam.py`` (#11987) pins the *streaming* dispatch path:
every exec of an agent process resolves a route first. This pins the other
shape — the **one-shot** face, ``run_lightweight_agent``, where the provider is
chosen per call rather than by the dispatch path.

A one-shot call that omits ``provider=`` inherits ``config.maintenance_provider``
(``runner_utils`` line "transport_provider = config.maintenance_provider if
provider is None else provider"), which is a dial an operator can set to
``gateway``. Such a face is governable and needs no entry here. A call that
passes a **literal** provider is not governable by any dial: the value is
compiled in, so an operator who locks a repository to one provider cannot move
it, and the lock silently stops being true.

**Enumerated by reference, per #11992.** The set is discovered by walking the
tree for literal ``provider=`` keywords, never hand-listed — the #11987 work
was bitten twice by predicates narrower than their subject, once by keying on
CLI literals and once by a ``glob`` that never reached a subdirectory.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"

#: The governed value. A face that names it routes through the resolver.
_GATEWAY = "gateway"

#: Literal non-gateway faces that are allowed to exist, and why. A new one
#: fails this gate: adding a row is where "should this be governed?" is asked.
_JUSTIFIED_UNGOVERNED_FACES: dict[str, str] = {
    "src/spec_reviewer.py": (
        "#11525 pinned this deliberately while changing the one-shot default "
        "to maintenance inheritance, so the pin PRESERVES prior behaviour "
        "rather than opting out of governance. Whether it should inherit "
        "instead is #11991's second criterion (maintenance-provider "
        "inheritance remains correct after the legacy paths are removed), so "
        "it is recorded here rather than changed under a different issue."
    ),
}


def _literal_provider_faces() -> tuple[tuple[str, int, str], ...]:
    """Every call passing a literal ``provider=``, as (path, line, value)."""
    faces = []
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "provider":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(
                    kw.value.value, str
                ):
                    faces.append(
                        (
                            path.relative_to(_SRC.parent).as_posix(),
                            node.lineno,
                            kw.value.value,
                        )
                    )
    return tuple(faces)


_FACES = _literal_provider_faces()

UNGOVERNED_FACES = tuple(
    (path, line, value) for path, line, value in _FACES if value != _GATEWAY
)
"""The subject: literal faces that do not name the governed seam."""


def test_the_sweep_sees_the_governed_faces_it_was_built_from() -> None:
    """Anti-vacuity: a predicate matching nothing would pass every case below."""
    governed = {path for path, _line, value in _FACES if value == _GATEWAY}

    assert {
        "src/implement_worker_runner.py",
        "src/plan_worker_runner.py",
        "src/review_worker_runner.py",
    } <= governed, f"the sweep stopped seeing the brokered runners: {governed}"


@pytest.mark.parametrize(
    ("path", "line", "value"),
    UNGOVERNED_FACES,
    ids=[f"{path}:{line}" for path, line, _v in UNGOVERNED_FACES],
)
def test_an_ungoverned_face_is_registered_with_a_reason(
    path: str, line: int, value: str
) -> None:
    reason = _JUSTIFIED_UNGOVERNED_FACES.get(path)

    assert reason, (
        f"{path}:{line} spawns with provider={value!r}, which no dial can "
        f"move: an operator locking a repository to one provider cannot "
        f"redirect this face and the lock stops being true. Either omit "
        f"provider= (inheriting config.maintenance_provider, which an "
        f"operator can set to 'gateway'), or register it in "
        f"_JUSTIFIED_UNGOVERNED_FACES with the reason it must stay pinned."
    )


def test_no_justification_is_stale() -> None:
    """A registered face that no longer exists must be removed, not left."""
    registered = set(_JUSTIFIED_UNGOVERNED_FACES)
    live = {path for path, _line, _value in UNGOVERNED_FACES}

    assert registered <= live, (
        f"these faces are registered but no longer ungoverned: "
        f"{sorted(registered - live)}. Drop the row — a stale entry silently "
        f"pre-approves a face someone adds back later."
    )
