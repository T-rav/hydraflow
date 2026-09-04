"""#12148: an unseeded catalog method-override must not leave a real subprocess.

Six catalog builders install a method override only when the scenario seeded the
port, and otherwise left the loop's REAL method in place — methods that build a
raw ``cmd = [...]``: ``gh run download``, ``make audit-json``,
``make trust-adversarial``. A scenario reaching one ran the real command against
the real repo. ``s17_skill_prompt_eval_clean_corpus`` did exactly that, while its
own docstring claimed a "corpus runner returns empty list" it never seeded — it
passed for a false reason with a subprocess behind it.

The pairs below are read out of the catalog itself, so a seventh override added
later is covered without editing this file.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

CATALOG = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scenarios"
    / "catalog"
    / "loop_registrations.py"
)


def _guarded_overrides() -> list[tuple[str, str, str]]:
    """(loop_name, attr, port_key) for every ``_override_or_refuse`` call site."""
    tree = ast.parse(CATALOG.read_text(encoding="utf-8"))

    builder_to_name: dict[str, str] = {}
    for node in ast.walk(tree):
        # `_BUILDERS: dict[str, Any] = {...}` is an AnnAssign (single `.target`),
        # not an Assign (`.targets` list) — matching only Assign found nothing,
        # which the known-positive test below caught.
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Dict):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "_BUILDERS" for t in targets):
            for k, v in zip(node.value.keys, node.value.values, strict=False):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Name):
                    builder_to_name[v.id] = k.value

    found: list[tuple[str, str, str]] = []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        name = builder_to_name.get(fn.name)
        if name is None:
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_override_or_refuse"
                and len(node.args) == 4
            ):
                attr, key = node.args[1], node.args[3]
                if isinstance(attr, ast.Constant) and isinstance(key, ast.Constant):
                    found.append((name, attr.value, key.value))
    return sorted(set(found))


_OVERRIDES = _guarded_overrides()


def test_the_sweep_finds_its_own_known_positive() -> None:
    """A derived list is only a guard while it still sees its source."""
    assert ("skill_prompt_eval", "_run_corpus", "skill_corpus_runner") in _OVERRIDES
    assert len(_OVERRIDES) >= 6


@pytest.mark.parametrize(("loop_name", "attr", "port_key"), _OVERRIDES)
@pytest.mark.asyncio
async def test_an_unseeded_raw_io_override_refuses(
    tmp_path: pathlib.Path, loop_name: str, attr: str, port_key: str
) -> None:
    """With nothing seeded, the attribute must refuse rather than run the command."""
    from unittest.mock import MagicMock  # noqa: PLC0415

    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415
    from tests.scenarios.catalog import LoopCatalog  # noqa: PLC0415
    from tests.scenarios.catalog.loop_registrations import (  # noqa: PLC0415
        ensure_registered,
    )

    ensure_registered()
    bg = make_bg_loop_deps(tmp_path)
    loop = LoopCatalog.instantiate(
        loop_name, ports={"github": MagicMock()}, config=bg.config, deps=bg.loop_deps
    )

    with pytest.raises(AssertionError, match=port_key):
        await getattr(loop, attr)()


@pytest.mark.parametrize(("loop_name", "attr", "port_key"), _OVERRIDES)
@pytest.mark.asyncio
async def test_a_seeded_override_is_installed_unchanged(
    tmp_path: pathlib.Path, loop_name: str, attr: str, port_key: str
) -> None:
    """The guard must not be over-broad: a seeded fake still lands."""
    from unittest.mock import AsyncMock, MagicMock  # noqa: PLC0415

    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415
    from tests.scenarios.catalog import LoopCatalog  # noqa: PLC0415
    from tests.scenarios.catalog.loop_registrations import (  # noqa: PLC0415
        ensure_registered,
    )

    ensure_registered()
    bg = make_bg_loop_deps(tmp_path)
    seeded = AsyncMock(return_value=[])
    loop = LoopCatalog.instantiate(
        loop_name,
        ports={"github": MagicMock(), port_key: seeded},
        config=bg.config,
        deps=bg.loop_deps,
    )

    assert getattr(loop, attr) is seeded
