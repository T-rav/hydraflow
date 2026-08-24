"""Structural gate: the audit never spells a source path as a flat literal.

#11709. ``scripts/hydraflow_audit/`` resolved 24 source probes as
``ctx.root / "src" / "<name>.py"`` while ``src/onboarding/kernel_writer.py``
stamps ``src/{pkg}/``. Every affected check missed at the probe on a stamped
repo and reported ``FAIL: <path> missing`` — a verdict about the audit's own
assumptions, not about the repo. HydraFlow is flat-src, so all 24 passed here
and were blind everywhere else.

The 24 conversions need a gate or they rot back. This is #6855's lesson: a fix
without a gate covering it is a fix with a countdown on it, and the guard that
issue asked for was never added at all.

What is forbidden
-----------------
A path expression that names ``src`` **and then something under it** as string
literals:

* ``ctx.root / "src" / "ports.py"``  — the module probe
* ``ctx.root / "src" / "domain"``    — the directory probe
* ``root.joinpath("src", "mockworld", "fakes")`` — the same, spelled out

What stays allowed
------------------
``src = ctx.root / "src"`` on its own, which is what the recursive scans
(P7.4/P7.5, P9.2/P9.3/P9.6/P9.8, P10.2) walk with ``rglob``. Those are already
layout-agnostic — P9.2 passing while its sibling P9.1 failed is how the class
announced itself.

The replacement is ``CheckContext.src_module`` / ``src_dir``
(:mod:`scripts.hydraflow_audit.layout`), which probes the flat spelling and
then ``src/<pkg>/``.

``_GRANDFATHERED`` is **empty** and must stay that way: every site was
converted, so a new entry means a new flat literal, and the fix for that is the
resolver, not the allowlist.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_AUDIT_PKG = Path("scripts") / "hydraflow_audit"

#: Relative paths (posix, under the audit package) still holding a flat source
#: literal. Empty after #11709 — shrink-only; growing it is the wrong fix.
_GRANDFATHERED: frozenset[str] = frozenset()

#: The floor on resolver adoption. A ratchet whose subject vanished passes
#: vacuously, so pin that the conversions are still there (#6855).
_MIN_RESOLVER_CALL_SITES = 24


def _literal(node: ast.expr) -> list[str | None]:
    """One path operand as segments — a ``"a/b"`` literal counts as two."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [part for part in node.value.split("/") if part]
    return [None]


def _path_segments(node: ast.expr) -> list[str | None]:
    """String segments of a ``a / "b" / "c"`` chain, ``None`` for non-literals.

    The base of the chain is dropped: ``ctx.root``, ``root`` and ``self.root``
    all lead to the same hazard, and the gate is about what follows. A
    ``Path("src")`` base and an embedded ``"src/ports.py"`` are expanded, so
    neither spelling evades the scan.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return [*_path_segments(node.left), *_literal(node.right)]
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "joinpath":
            base = _path_segments(func.value)
            args = [seg for arg in node.args for seg in _literal(arg)]
            return [*base, *args]
        if isinstance(func, ast.Name) and func.id == "Path":
            return [seg for arg in node.args for seg in _literal(arg)]
    return []


def _is_flat_source_literal(node: ast.expr) -> bool:
    """True when the expression names ``src`` and a literal child of it."""
    segments = _path_segments(node)
    for index, segment in enumerate(segments):
        if segment == "src" and index + 1 < len(segments):
            return segments[index + 1] is not None
    return False


def _offenders(root: Path) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    audit_root = root / _AUDIT_PKG
    for py in sorted(audit_root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        lines = sorted(
            {
                node.lineno
                for node in ast.walk(tree)
                if isinstance(node, ast.BinOp | ast.Call)
                and _is_flat_source_literal(node)
            }
        )
        if lines:
            found[py.relative_to(audit_root).as_posix()] = lines
    return found


def test_no_flat_source_path_literal_in_the_audit(real_repo_root: Path) -> None:
    """Source modules resolve through ``ctx.src_module`` / ``src_dir`` (#11709)."""
    offenders = {
        rel: lines
        for rel, lines in _offenders(real_repo_root).items()
        if rel not in _GRANDFATHERED
    }
    assert offenders == {}, (
        f"Flat `src/<name>` path literal in the audit: {offenders}. "
        "Use ctx.src_module('<name>') / ctx.src_dir('<parts>') — a flat "
        "literal is blind to every repo the greenfield kernel writer stamps "
        "(#11709). A bare `ctx.root / 'src'` walked with rglob is fine."
    )


def test_grandfather_list_is_empty(real_repo_root: Path) -> None:
    """Shrink-only, and it started at zero. Guard both directions."""
    stale = sorted(_GRANDFATHERED - set(_offenders(real_repo_root)))
    assert stale == [], f"No longer offenders: {stale}. Drop them from the list."
    assert not _GRANDFATHERED, (
        "The #11709 conversion left no flat literals. A new entry here means a "
        "new one was written; convert it instead of grandfathering it."
    )


def test_the_resolver_is_still_the_thing_being_used(real_repo_root: Path) -> None:
    """Guard the guard: an empty scan must not be able to pass vacuously."""
    audit_root = real_repo_root / _AUDIT_PKG
    assert (audit_root / "layout.py").is_file(), "the resolver module is gone"
    call_sites = sum(
        text.count("ctx.src_module(") + text.count("ctx.src_dir(")
        for py in audit_root.rglob("*.py")
        if "__pycache__" not in py.parts
        for text in [py.read_text(encoding="utf-8")]
    )
    assert call_sites >= _MIN_RESOLVER_CALL_SITES, (
        f"only {call_sites} layout-aware call sites, floor is "
        f"{_MIN_RESOLVER_CALL_SITES}. The #11709 conversions were removed or "
        "reverted, which would let the scan above pass with nothing to find."
    )


# --- detector self-tests --------------------------------------------------

_FORBIDDEN_SHAPES = [
    pytest.param('p = ctx.root / "src" / "ports.py"\n', id="module-literal"),
    pytest.param('p = ctx.root / "src" / "domain"\n', id="directory-literal"),
    pytest.param('p = root / "src" / "mockworld" / "fakes"\n', id="nested-literal"),
    pytest.param('p = self.root / "src" / "config.py"\n', id="attribute-base"),
    pytest.param('p = ctx.root.joinpath("src", "mockworld", "fakes")\n', id="joinpath"),
    pytest.param(
        'CANDIDATES = [ctx.root / "src" / "a.py", ctx.root / "src" / "b.py"]\n',
        id="inside-a-list",
    ),
    pytest.param('p = Path("src") / "ports.py"\n', id="path-constructor-base"),
    pytest.param('p = ctx.root / "src/ports.py"\n', id="embedded-separator"),
    pytest.param(
        'p = ctx.root.joinpath("src/mockworld", "fakes")\n', id="joinpath-embedded"
    ),
]

_ALLOWED_SHAPES = [
    pytest.param('src = ctx.root / "src"\n', id="bare-src-root"),
    pytest.param('src = ctx.root.joinpath("src")\n', id="bare-src-joinpath"),
    pytest.param('p = ctx.root / "src" / name\n', id="variable-segment"),
    pytest.param("p = src.joinpath(pkg, *parts)\n", id="starred-segments"),
    pytest.param('p = ctx.root / "tests" / "scenarios"\n', id="not-src"),
    pytest.param('p = ctx.src_module("ports")\n', id="the-resolver"),
]


def _detect(body: str) -> bool:
    tree = ast.parse(body)
    return any(
        _is_flat_source_literal(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp | ast.Call)
    )


@pytest.mark.parametrize("body", _FORBIDDEN_SHAPES)
def test_detector_catches_every_flat_literal_shape(body: str) -> None:
    assert _detect(body)


@pytest.mark.parametrize("body", _ALLOWED_SHAPES)
def test_detector_ignores_layout_agnostic_shapes(body: str) -> None:
    assert not _detect(body)
