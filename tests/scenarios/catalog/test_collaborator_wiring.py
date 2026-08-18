"""Recurrence guard (#11424): catalog builders must forward every optional
collaborator kwarg accepted by the loop's constructor, not just the
required ones.

A builder that accepts ``ports`` but never forwards one of the loop's
*optional* constructor collaborators still instantiates fine — so
``tests/scenarios/catalog/test_loop_instantiation.py`` stays green — but the
collaborator stays permanently ``None``, and any phase gated on
``self._collaborator is not None`` silently goes unreachable in every
MockWorld scenario. Add a row here whenever a new such gap is found or
introduced.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.scenarios.catalog import LoopCatalog
from tests.scenarios.catalog.loop_registrations import ensure_registered

# (loop_name, port_key, attr_name) — sentinel seeded at ports[port_key] must
# land on instance.attr_name after LoopCatalog.instantiate(loop_name, ...).
_COLLABORATOR_WIRING_TABLE = [
    ("escape_ledger", "auto_diagnoser", "_auto_diagnoser"),
    ("skill_prompt_eval", "refine_llm", "_refine_llm"),
    ("diagnostic", "workspace", "_workspaces"),
]


@pytest.fixture(autouse=True)
def _ensure_registered() -> Iterator[None]:
    ensure_registered()
    yield


@pytest.mark.parametrize(
    ("loop_name", "port_key", "attr_name"), _COLLABORATOR_WIRING_TABLE
)
def test_builder_forwards_optional_collaborator(
    tmp_path: Path, loop_name: str, port_key: str, attr_name: str
) -> None:
    """A sentinel seeded at ports[port_key] must land on instance.attr_name."""
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

    bg = make_bg_loop_deps(tmp_path)
    sentinel = MagicMock(name=f"sentinel-{port_key}")
    ports: dict = {"github": MagicMock(), port_key: sentinel}

    instance = LoopCatalog.instantiate(
        loop_name, ports=ports, config=bg.config, deps=bg.loop_deps
    )

    assert getattr(instance, attr_name) is sentinel, (
        f"{loop_name!r} builder did not forward ports[{port_key!r}] onto "
        f"instance.{attr_name} — see #11424"
    )
