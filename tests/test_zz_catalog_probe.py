"""Throwaway probe: which catalog-built loops carry a None collaborator, and
which of those would lazily CONSTRUCT something on first use."""

import ast
import inspect
from unittest.mock import MagicMock


def test_probe(tmp_path):
    from tests.helpers import make_bg_loop_deps
    from tests.scenarios.catalog import LoopCatalog
    from tests.scenarios.catalog.loop_registrations import ensure_registered

    ensure_registered()
    bg = make_bg_loop_deps(tmp_path)
    names = (
        sorted(LoopCatalog.registered_names())
        if hasattr(LoopCatalog, "registered_names")
        else []
    )
    if not names:
        from tests.scenarios.catalog import loop_catalog as lc

        reg = getattr(lc, "_REGISTRY", None) or getattr(LoopCatalog, "_registry", None)
        names = sorted(reg) if reg else []
    print(f"\nLOOPS={len(names)}")

    rows = []
    for name in names:
        try:
            inst = LoopCatalog.instantiate(
                name, ports={"github": MagicMock()}, config=bg.config, deps=bg.loop_deps
            )
        except Exception as e:
            print(f"SKIP {name} {type(e).__name__}")
            continue
        cls = type(inst)
        # per-CLASS lazy construction: `self._x = Thing(...)` anywhere in the class
        try:
            src = inspect.getsource(cls)
            tree = ast.parse(src)
        except (OSError, SyntaxError, IndentationError):
            continue
        builds = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                t = n.targets[0]
                f = n.value.func
                nm = (
                    f.id
                    if isinstance(f, ast.Name)
                    else (f.attr if isinstance(f, ast.Attribute) else None)
                )
                if isinstance(t, ast.Attribute) and t.attr.startswith("_") and nm:
                    builds[t.attr] = nm
        for attr, ctor in sorted(builds.items()):
            if getattr(inst, attr, "MISSING") is None:
                rows.append((name, attr, ctor))
    print(f"NONE_AND_LAZILY_BUILT={len(rows)}")
    for name, attr, ctor in rows:
        print(f"ROW {name} {attr} {ctor}")
