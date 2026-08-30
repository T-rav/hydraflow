"""Regression: kernel template bodies must resolve through the package, not `__file__`.

When the stamped-document bodies moved out of Python string literals into
files, the first version of `bodies_root()` derived their location by walking
up from `__file__`::

    Path(__file__).resolve().parent.parent / "hydraflow_resources/..."

That expression means two different things depending on where the module sits:
``<repo>`` from ``<repo>/src/onboarding/x.py``, but ``lib/python3.11/`` from
``site-packages/onboarding/x.py``. It is the exact idiom #11589 removed from
eight modules after the wheel became importable, and it fails SILENTLY in a
source checkout — every test passed, and a hand-run wheel build even confirmed
the files were *present*, because presence is not the same question as whether
the lookup finds them.

`tests/architecture/test_wheel_console_script.py` catches the idiom by shape.
This pins the behaviour: the bodies are reachable through the packaged
resource accessor, and every template a writer asks for is actually there.
"""

from __future__ import annotations

import ast
from pathlib import Path

from onboarding import kernel_templates

REPO_ROOT = Path(__file__).resolve().parents[2]
WRITERS = (
    "src/onboarding/kernel_writer.py",
    "src/onboarding/templating.py",
    "src/onboarding/design_ai.py",
)


def test_bodies_resolve_through_the_packaged_resource_accessor() -> None:
    root = kernel_templates.bodies_root()
    assert root.is_dir(), f"kernel template bodies not reachable at {root}"

    # Anti-vacuity: an empty directory would satisfy "it resolves".
    bodies = [p for p in root.rglob("*.tmpl") if p.is_file()]
    assert len(bodies) >= 30, (
        f"only {len(bodies)} template bodies under {root}; the writers stamp "
        "far more documents than that"
    )


def test_every_template_a_writer_asks_for_exists() -> None:
    """A render() call naming a body that is not on disk is a stamp that dies.

    `render` raises rather than emitting a half-substituted file, so a missing
    body fails loudly at stamp time — but that is a failure in a child repo's
    creation, discovered by whoever was unlucky. This finds it here instead.
    """
    missing: list[str] = []
    seen = 0
    for relative in WRITERS:
        tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "render"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                name = node.args[0].value
                seen += 1
                if not (kernel_templates.bodies_root() / name).is_file():
                    missing.append(f"{relative}:{node.lineno} -> {name}")
    # Anti-vacuity: if the walk matched nothing, "no missing bodies" is true
    # of an empty set and this test would pass against writers that had gone
    # back to inline literals entirely.
    assert seen >= 25, (
        f"only {seen} render() calls found across {list(WRITERS)}; the AST "
        "walk is not seeing its subject"
    )
    assert not missing, (
        "render() calls naming bodies that do not exist:\n  " + "\n  ".join(missing)
    )
