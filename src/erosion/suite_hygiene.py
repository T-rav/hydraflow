"""Pure test-hygiene sensor — structural redundancy in the test suite.

"Do we need all 19k tests?" is not answerable by a clock-driven deletion
pass, but two shapes of redundancy are mechanical and safe to name:

* **Parametrize candidates** — ≥ ``min_group`` test functions in ONE file whose
  bodies are identical once literal values and the docstring are normalized
  away. Identifiers are kept: two tests that call *different* functions are
  different tests, not a group (only the values vary in a parametrize case). They are one ``pytest.mark.parametrize``
  waiting to happen; each extra copy is a line of suite mass that buys no
  new assertion.
* **Cross-file duplicates** — the same test *name* with an identical normalized
  body in two or more files: copy-paste that survived a move or a split.

Same purity contract as ``erosion.mass.compute``: ``compute`` reads an explicit
``{path: text}`` mapping and never touches the filesystem; ``collect_tests``
is the adapter. Unparseable files are skipped, never raised.

Deliberately NOT here: "does this test ever fail" (that is the mutation
gauntlet, ADR-0125, on demand) and anything that runs pytest.
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from erosion.models import CrossFileDuplicate, ParametrizeGroup, SuiteHygieneFinding
from pytest_collection import collected_test_globs

#: This repo's root — ``src/erosion/suite_hygiene.py`` -> up three.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Minimum identical tests in one file before they are reported as a parametrize group.
DEFAULT_MIN_GROUP = 3

_SKIP_DIRS = frozenset({"__pycache__", "node_modules", ".venv"})


_SKIP_FIELDS = frozenset(
    {
        "lineno",
        "col_offset",
        "end_lineno",
        "end_col_offset",
        "type_comment",
        "ctx",
    }
)


def _dump(node: object) -> str:
    """Structural dump with literal VALUES erased (kept: their type) and identifiers kept."""
    if isinstance(node, ast.Constant):
        return f"C:{type(node.value).__name__}"
    if isinstance(node, ast.AST):
        parts = [
            f"{field}={_dump(value)}"
            for field, value in ast.iter_fields(node)
            if field not in _SKIP_FIELDS
        ]
        return f"{type(node).__name__}({','.join(parts)})"
    if isinstance(node, list):
        return "[" + ",".join(_dump(item) for item in node) + "]"
    return repr(node)


def _body_without_docstring(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.stmt]:
    body = fn.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body or [ast.Pass()]


def _signature_of(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Digest of *fn*'s normalized structure — name, docstring and return annotation dropped."""
    dumped = (
        f"{type(fn).__name__}(args={_dump(fn.args)},"
        f"body={_dump(_body_without_docstring(fn))},"
        f"decorators={_dump(fn.decorator_list)})"
    )
    return hashlib.sha1(dumped.encode("utf-8"), usedforsecurity=False).hexdigest()


def normalized_signature(source: str) -> str:
    """Signature of the first function in *source* — the unit the sensor compares.

    Exposed for tests and tooling; ``compute`` applies the same normalization
    to every ``test_*`` function it finds.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return _signature_of(node)
    raise ValueError("no function in source")


def _test_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    ]


def compute(
    tests: Mapping[str, str], *, min_group: int = DEFAULT_MIN_GROUP
) -> SuiteHygieneFinding:
    """Find parametrize groups and cross-file duplicates across *tests*."""
    groups: list[ParametrizeGroup] = []
    by_name_sig: dict[tuple[str, str], set[str]] = defaultdict(set)
    total_tests = 0
    for path in sorted(tests):
        try:
            tree = ast.parse(tests[path])
        except (SyntaxError, ValueError):
            continue
        per_sig: dict[str, list[str]] = defaultdict(list)
        for fn in _test_functions(tree):
            total_tests += 1
            sig = _signature_of(fn)
            per_sig[sig].append(fn.name)
            by_name_sig[(fn.name, sig)].add(path)
        for names in per_sig.values():
            if len(names) >= min_group:
                groups.append(ParametrizeGroup(path=path, names=tuple(names)))
    groups.sort(key=lambda g: (-len(g.names), g.path))
    cross = sorted(
        (
            CrossFileDuplicate(name=name, paths=tuple(sorted(paths)))
            for (name, _sig), paths in by_name_sig.items()
            if len(paths) >= 2
        ),
        key=lambda d: (d.name, d.paths),
    )
    return SuiteHygieneFinding(
        total_files=len(tests),
        total_tests=total_tests,
        parametrize_groups=tuple(groups),
        cross_file_duplicates=tuple(cross),
    )


def collect_tests(
    tests_dir: Path, globs: tuple[str, ...] | None = None
) -> dict[str, str]:
    """Read every pytest-collected module under *tests_dir* (impure), keyed by ``<tests_dir.name>/<relative>`` posix path.

    Matches the repo's ``python_files`` globs recursively; skips bytecode
    caches and vendored trees. The globs come from
    :func:`pytest_collection.collected_test_globs` rather than a constant here,
    so this sensor and the anti-skip guard cannot disagree about what a test
    file is — they read the same key of the same file.

    *globs* defaults to what THIS repo declares, resolved from its own
    ``pyproject.toml``. Deliberately not resolved from ``tests_dir.parent``: a
    directory with no pyproject beside it — a tmp fixture, an export — would
    fall back to pytest's bare defaults and drop every ``regression_*.py`` from
    the count without saying so. Silently measuring less than you claim to is
    the failure this module exists to detect, not to commit. Callers auditing a
    different repo pass that repo's globs explicitly.
    """
    if globs is None:
        globs = collected_test_globs(_REPO_ROOT)
    out: dict[str, str] = {}
    for glob in globs:
        for path in tests_dir.rglob(glob):
            rel = path.relative_to(tests_dir)
            if _SKIP_DIRS.intersection(rel.parts[:-1]):
                continue
            key = (Path(tests_dir.name) / rel).as_posix()
            out[key] = path.read_text(encoding="utf-8", errors="replace")
    return out
