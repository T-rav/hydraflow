"""Probe 2: None attributes used as `self._x or <real thing>` — the fallback
shape a lazy-construction sweep cannot see."""

import ast
import inspect
from unittest.mock import MagicMock


def test_probe(tmp_path):
    from tests.helpers import make_bg_loop_deps
    from tests.scenarios.catalog import LoopCatalog
    from tests.scenarios.catalog.loop_registrations import ensure_registered

    ensure_registered()
    bg = make_bg_loop_deps(tmp_path)
    from tests.scenarios.catalog import loop_catalog as lc

    reg = getattr(lc, "_REGISTRY", None) or getattr(LoopCatalog, "_registry", None)
    names = sorted(reg)

    rows = []
    for name in names:
        try:
            inst = LoopCatalog.instantiate(
                name, ports={"github": MagicMock()}, config=bg.config, deps=bg.loop_deps
            )
        except Exception:
            continue
        cls = type(inst)
        try:
            tree = ast.parse(inspect.getsource(cls))
        except (OSError, SyntaxError, IndentationError):
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.BoolOp) or not isinstance(n.op, ast.Or):
                continue
            first = n.values[0]
            if not (isinstance(first, ast.Attribute) and first.attr.startswith("_")):
                continue
            if getattr(inst, first.attr, "MISSING") is not None:
                continue
            alt = ast.unparse(n.values[1])[:52]
            rows.append((name, first.attr, alt))
    print(f"\nOR_FALLBACK_ON_NONE={len(rows)}")
    for r in sorted(set(rows)):
        print(f"ROW {r[0]} {r[1]} -> {r[2]}")
