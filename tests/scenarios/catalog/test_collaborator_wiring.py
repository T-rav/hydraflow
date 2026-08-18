"""Recurrence guard for #11416's silent-omission shape.

A catalog builder that accepts a port key but never forwards it to the
loop constructor leaves an *optional* collaborator permanently ``None`` —
the loop instantiates fine (so ``test_loop_instantiation.py`` stays green)
but a whole phase gated on ``self._collaborator is not None`` goes quietly
unreachable in every MockWorld scenario. ``_build_repo_wiki`` had exactly
this shape for ``wiki_compiler`` (silently gating Phase 2/8 compilation).

This is a table, not a one-off assertion, so auditing another builder for
the same shape means adding a row here rather than a new test file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog.loop_registrations import ensure_registered

# (loop name, [optional collaborator attrs the builder must forward when
# the matching port key is present]). The loop's constructor param name
# and its stored attribute name are assumed to match ``_<port_key>``.
_COLLABORATOR_WIRING_TABLE: list[tuple[str, list[str]]] = [
    ("repo_wiki", ["wiki_compiler", "state", "tribal_store"]),
]


@pytest.fixture(autouse=True)
def _ensure_registered() -> Iterator[None]:
    ensure_registered()
    yield


@pytest.mark.parametrize(
    ("loop_name", "collaborators"),
    _COLLABORATOR_WIRING_TABLE,
    ids=[name for name, _ in _COLLABORATOR_WIRING_TABLE],
)
def test_builder_forwards_seeded_collaborators(
    tmp_path: Path, loop_name: str, collaborators: list[str]
) -> None:
    from base_background_loop import LoopDeps
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    loop_deps = LoopDeps(
        event_bus=bg.bus,
        stop_event=bg.stop_event,
        status_cb=bg.status_cb,
        enabled_cb=bg.enabled_cb,
        sleep_fn=AsyncMock(),
    )

    sentinels = {name: object() for name in collaborators}
    ports: dict = dict(sentinels)

    instance = LoopCatalog.instantiate(
        loop_name, ports=ports, config=bg.config, deps=loop_deps
    )

    for name, sentinel in sentinels.items():
        attr = f"_{name}"
        assert getattr(instance, attr, None) is sentinel, (
            f"{loop_name!r} builder did not forward ports[{name!r}] to the "
            f"loop's {attr!r} attribute — this collaborator is silently "
            "dead in every MockWorld scenario"
        )
