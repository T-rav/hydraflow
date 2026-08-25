"""Structural gate: only ``layout.py`` may spell the source directory (#11709).

The audit resolved 24 source probes as flat literals — ``ctx.root / "src" /
"<name>.py"`` — while ``src/onboarding/kernel_writer.py`` stamps ``src/{pkg}/``.
Every affected check missed at the probe on a stamped repo and reported
``FAIL: <path> missing``: a verdict about the audit's own assumptions, not about
the repo. HydraFlow is flat-src, so all 24 passed here and were blind everywhere
else. The conversions need a gate or they rot back — #6855's lesson, where the
guard that issue asked for was never added at all.

Why this gate matches a LITERAL, not a shape
---------------------------------------------
The first version of this file matched AST shapes: a ``/``-chain, then also
``joinpath``, then also ``os.path.join``, then also ``Path("src")``, then also
f-strings, then also ``+`` concatenation. Five review passes found five more
spellings it could not see, including:

    pathlib.Path("src") / name        # Attribute callee, not a bare Name
    PurePath("src") / name            # bare Name, but not spelled "Path"
    _SRC = "src"; root / _SRC / name  # the "src" segment hoisted to a constant

That list was never going to close. **A gate that enumerates shapes is the same
enumeration-drift disease this PR exists to fix** (cf. #11715 for the
branch-protection instance). Hoisting a repeated ``"src"`` to a module constant
is an ordinary DRY refactor, and under a shape-matching gate it silently
disarmed the whole thing.

So the rule is inverted, and it is one sentence:

    The string ``src`` appears in exactly ONE module — ``layout.py``.

Every spelling of the hazard, known or not, must contain that literal in order
to name the directory at all. ``PurePosixPath("src")`` contains it. ``_SRC =
"src"`` contains it. ``f"src/{name}.py"`` contains it. A shape nobody has
thought of yet contains it. There is nothing left to enumerate, and the
detector below is ~15 lines instead of ~90.

What replaced the literals
--------------------------
``CheckContext.src_root()`` for a recursive scan root (P7.4/P7.5,
P9.2/P9.3/P9.6/P9.8, P10.2 — already layout-agnostic, since ``rglob`` from
``src/`` reaches ``src/<pkg>/**``), and ``src_module`` / ``src_dir`` for the
probes that name a module. ``layout.SOURCE_DIR_NAME`` for the one remaining
consumer outside a ``CheckContext`` (the ``__init__`` sys.path bootstrap).

``_GRANDFATHERED`` is **empty** and must stay that way: every site was
converted, so a new entry means a new literal, and the fix for that is the
vocabulary, not the allowlist.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_AUDIT_PKG = Path("scripts") / "hydraflow_audit"

#: The one module allowed to spell the source directory.
_OWNER = "layout.py"

#: Relative paths (posix, under the audit package) that still spell it anyway.
#: Empty after #11709 — shrink-only; growing it is the wrong fix.
_GRANDFATHERED: frozenset[str] = frozenset()

#: ``src`` as a path token: the bare directory name, or the head of a path.
#: Deliberately NOT a bare substring test — ``"source"``, ``"src_root"`` and
#: prose like ``"no *_DATA_ROOT override found in src/"`` (a trailing slash with
#: no child) are not hazards, and a gate that flagged them would be relaxed into
#: uselessness the first time it did.
_SRC_TOKEN_RE = re.compile(r"(?<![\w/.-])src(?:/[A-Za-z_][\w.-]*|$)")

#: Stand-in for a runtime slot inside a composed string, so ``f"src/{name}.py"``
#: renders as a path with a child rather than a bare ``"src/"``.
_HOLE = "X"


def _string_skeleton(node: ast.expr) -> str:
    """The literal skeleton of a composed string, runtime slots as ``X``.

    Reassembles f-strings and ``+`` chains, because a ``src`` split across two
    literals (``"src/" + name``) is one path to a reader and two ``Constant``
    nodes to a scanner. Implicit adjacent-literal concatenation needs no arm:
    CPython folds ``"src/" "ports.py"`` into one ``Constant`` at parse time.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else _HOLE
    if isinstance(node, ast.JoinedStr):
        return "".join(_string_skeleton(part) for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _string_skeleton(node.left) + _string_skeleton(node.right)
    return _HOLE


def _docstring_constants(tree: ast.AST) -> set[int]:
    """``id()`` of every docstring Constant — prose may name a flat path."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            ids.add(id(body[0].value))
    return ids


def _composed_strings(tree: ast.AST) -> list[ast.expr]:
    """Every string expression to skeletonize, outermost composition only.

    The children of a ``+`` chain or f-string are skipped: the outermost node's
    skeleton already contains them, and reporting both duplicates the line.
    """
    inner: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            inner.update(id(part) for part in node.values)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            inner.update({id(node.left), id(node.right)})
    return [
        node
        for node in ast.walk(tree)
        if id(node) not in inner
        and (
            (isinstance(node, ast.Constant) and isinstance(node.value, str))
            or isinstance(node, ast.JoinedStr)
            or (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add))
        )
    ]


def _offending_lines(tree: ast.AST) -> list[int]:
    """Lines naming the source directory as a literal, outside docstrings."""
    exempt = _docstring_constants(tree)
    return sorted(
        {
            node.lineno
            for node in _composed_strings(tree)
            if id(node) not in exempt and _SRC_TOKEN_RE.search(_string_skeleton(node))
        }
    )


def _offenders(root: Path) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    audit_root = root / _AUDIT_PKG
    for py in sorted(audit_root.rglob("*.py")):
        rel = py.relative_to(audit_root).as_posix()
        if "__pycache__" in py.parts or rel == _OWNER:
            continue
        lines = _offending_lines(ast.parse(py.read_text(encoding="utf-8")))
        if lines:
            found[rel] = lines
    return found


def test_only_the_owner_spells_the_source_directory(real_repo_root: Path) -> None:
    """``layout.py`` owns the literal; everything else uses the vocabulary."""
    offenders = {
        rel: lines
        for rel, lines in _offenders(real_repo_root).items()
        if rel not in _GRANDFATHERED
    }
    assert offenders == {}, (
        f"Source-directory literal outside {_OWNER}: {offenders}. Use "
        "ctx.src_root() for a recursive scan root, ctx.src_module('<name>') / "
        "ctx.src_dir('<parts>') for a module or directory probe, or "
        "layout.SOURCE_DIR_NAME outside a CheckContext. A hand-spelled literal "
        "is blind to every repo the greenfield kernel writer stamps (#11709)."
    )


def test_grandfather_list_is_empty(real_repo_root: Path) -> None:
    """Shrink-only, and it started at zero. Guard both directions."""
    stale = sorted(_GRANDFATHERED - set(_offenders(real_repo_root)))
    assert stale == [], f"No longer offenders: {stale}. Drop them from the list."
    assert not _GRANDFATHERED, (
        "The #11709 conversion left no literals outside the owner. A new entry "
        "here means a new one was written; convert it instead."
    )


def test_the_owner_still_owns_it(real_repo_root: Path) -> None:
    """Guard the exemption: an emptied owner must not silently pass the scan."""
    owner = real_repo_root / _AUDIT_PKG / _OWNER
    assert owner.is_file(), f"{_OWNER} is gone — the resolver was removed"
    assert _offending_lines(ast.parse(owner.read_text(encoding="utf-8"))), (
        f"{_OWNER} no longer spells the source directory. Either the constant "
        "moved (point _OWNER at its new home) or the resolver was gutted — "
        "which would let the scan above pass with nothing left to find."
    )


#: Floor on resolver adoption. A ratchet whose subject vanished passes
#: vacuously, so pin that the conversions are still there (#6855).
_MIN_RESOLVER_CALL_SITES = 24


def test_the_resolver_is_still_the_thing_being_used(real_repo_root: Path) -> None:
    """Guard the guard: count real CALLS, not mentions in prose."""
    audit_root = real_repo_root / _AUDIT_PKG
    wanted = {"src_root", "src_module", "src_dir"}
    call_sites = 0
    for py in audit_root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in wanted
            ):
                call_sites += 1
    assert call_sites >= _MIN_RESOLVER_CALL_SITES, (
        f"only {call_sites} layout-aware call sites, floor is "
        f"{_MIN_RESOLVER_CALL_SITES}. The #11709 conversions were removed or "
        "reverted, which would let the scan above pass with nothing to find."
    )


# --- detector self-tests ---------------------------------------------------
#
# Every spelling any review pass found, plus the ones that were only ever
# hypothetical. They are all caught by the SAME one-line rule — that is the
# point of the list: it is evidence the rule generalises, not a set of arms.

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
    pytest.param('p = Path("src") / "ports.py"\n', id="path-constructor"),
    # --- pass-4 evasions: constructor spellings a Name=="Path" test missed ---
    pytest.param('p = pathlib.Path("src") / name\n', id="qualified-path-ctor"),
    pytest.param('p = PurePath("src") / name\n', id="purepath-ctor"),
    pytest.param('p = PurePosixPath("src") / name\n', id="pureposixpath-ctor"),
    pytest.param('p = PosixPath("src") / name\n', id="posixpath-ctor"),
    pytest.param('p = WindowsPath("src") / name\n', id="windowspath-ctor"),
    pytest.param('p = PureWindowsPath("src") / name\n', id="purewindowspath-ctor"),
    # --- pass-4 evasion: the "src" segment itself hoisted to a variable ---
    pytest.param('_SRC = "src"\np = ctx.root / _SRC / "ports.py"\n', id="src-hoisted"),
    pytest.param(
        '_SRC = "src"\np = ctx.root.joinpath(_SRC, name)\n', id="src-hoisted-joinpath"
    ),
    # --- earlier passes ---
    pytest.param('p = ctx.root / "src/ports.py"\n', id="embedded-separator"),
    pytest.param(
        'p = ctx.root.joinpath("src/mockworld", "fakes")\n', id="joinpath-embedded"
    ),
    pytest.param('p = ctx.root / "src" / name\n', id="variable-child"),
    pytest.param('p = ctx.root / f"src/{name}.py"\n', id="fstring-whole-path"),
    pytest.param('p = ctx.root / ("src/" + name + ".py")\n', id="concatenated-path"),
    pytest.param(
        'p = os.path.join(str(ctx.root), "src", "ports.py")\n', id="os-path-join"
    ),
    pytest.param('ui_only = path.startswith("src/ui/")\n', id="string-prefix"),
    pytest.param('UI_TEST_RE = re.compile(r"^src/ui/.*")\n', id="regex-source"),
    pytest.param('_PORTS_REL = "src/ports.py"\n', id="named-constant"),
]

_ALLOWED_SHAPES = [
    pytest.param("src = ctx.src_root()\n", id="the-scan-root-vocabulary"),
    pytest.param('p = ctx.src_module("ports")\n', id="the-module-vocabulary"),
    pytest.param('p = ctx.src_dir("mockworld", "fakes")\n', id="the-dir-vocabulary"),
    pytest.param("p = src.joinpath(pkg, *parts)\n", id="starred-segments"),
    pytest.param('p = ctx.root / "tests" / "scenarios"\n', id="not-src"),
    pytest.param('p = ctx.root / "source" / "x.py"\n', id="src-is-not-a-substring"),
    pytest.param(
        'm = "no *_DATA_ROOT override found in src/"\n', id="prose-trailing-slash"
    ),
    pytest.param('m = f"{ctx.rel(p)} missing"\n', id="fstring-resolved-path"),
    pytest.param('m = "looked under " + probed + "/ and tests/"\n', id="concat-clean"),
    pytest.param('def f():\n    """Probes src/ports.py."""\n', id="docstring-prose"),
]


def _detect(body: str) -> bool:
    return bool(_offending_lines(ast.parse(body)))


@pytest.mark.parametrize("body", _FORBIDDEN_SHAPES)
def test_detector_catches_every_spelling(body: str) -> None:
    assert _detect(body)


@pytest.mark.parametrize("body", _ALLOWED_SHAPES)
def test_detector_ignores_the_vocabulary_and_prose(body: str) -> None:
    assert not _detect(body)
