"""Pure concept-scatter sensor (#10106): a newly-added symbol spread across many modules.

v1 heuristic — PROVISIONAL, not the final definition; the parent issue
(#10106) explicitly calls the precise "concept implemented in multiple
places" definition an open design question, tracked on epic #10104.
`compute` picks ONE concrete signal to ship first: a newly-introduced
identifier (function/class/constant name) that a single change adds to
K>=3 DISTINCT modules — the same new symbol being independently
reimplemented in many places, rather than defined once and shared, is a
shotgun-duplication / coupling-erosion smell. The other candidate signals
#10106 names (near-duplicate code blocks via jscpd, historically
change-coupled files) are explicitly OUT of this v1's scope; a future
revision may fold them in or supersede this heuristic entirely.

Mirrors the purity contract of `erosion.spread.compute` (#10105): takes an
explicit *mapping* of changed-file -> newly-added symbol names rather than
a diff or git range, so it's unit-testable with synthetic inputs and has
no git/AST dependency in the core. `added_symbols_for_range` is the thin
git+regex adapter that wraps it for real commit ranges; `compute` itself
never shells out or touches the filesystem. Reuses the SAME
`arch.extractors.modules.package_of`-backed file->module resolution
`erosion.spread` uses (via its `_module_for_file` helper) rather than
hand-rolling a second mapping.

Do NOT wire this into `disturbance.registry.DIMENSIONS` — for the same
reason `erosion.spread` isn't (see that module's docstring):
`ViolationDetector.detect(repo_root)` is a per-file static snapshot; this
sensor is change-scoped. The caretaker loop and issue-filing actuator
that consume `ScatterFinding` are sibling issue #10107, not this one.
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path

from arch._models import ModuleGraph
from erosion.models import ScatteredSymbol, ScatterFinding
from erosion.spread import _module_for_file
from git_timeouts import GIT_READONLY_TIMEOUT_S

#: Default K: a newly-added symbol must appear in at least this many
#: DISTINCT modules for one change to be flagged as "scattered." This is
#: #10106's v1 definition, named here as a single constant so it's easy to
#: retune without touching call sites; refinable per the epic's design pass.
DEFAULT_SCATTER_THRESHOLD = 3

# Light line-regexes over a diff's added (`+`) lines — NOT a full AST parse,
# since a diff hunk is a source fragment, not standalone-parseable source.
# Deliberately narrow: top-level-*looking* `def`/`class`/ALL_CAPS-assignment
# lines only (indentation is not required, so methods match too — a v1
# simplification). Dunder names (`__init__`, `__repr__`, ...) are excluded
# below; they're structural boilerplate, not "concept" names, and would
# otherwise dominate the signal with noise.
_DEF_RE = re.compile(r"^\s*def\s+(\w+)\s*\(")
_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*[:\(]")
_CONST_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*(?::[^=]+)?=(?!=)")
_DIFF_NEW_FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(.+)$")


def compute(
    added_symbols_by_file: dict[str, list[str]],
    module_graph: ModuleGraph,
    *,
    threshold: int = DEFAULT_SCATTER_THRESHOLD,
) -> ScatterFinding:
    """Pure: which newly-added symbols this change scattered across >= threshold modules.

    *added_symbols_by_file* maps a repo-root-relative changed-file path (as
    `erosion.spread.compute` takes) to the newly-added identifier names in
    that file for this change (function/class/constant names — a real
    adapter like `added_symbols_for_range` judges what counts as "added";
    synthetic tests may pass whatever list they like). *module_graph* is
    used exactly as `erosion.spread.compute` uses it: each file resolves to
    its module via `arch.extractors.modules.package_of`, keeping only
    modules the graph actually knows about — files that don't resolve land
    in ``unmapped_files`` and never count toward a symbol's module tally.

    A symbol reused across multiple FILES within the SAME module does not
    count as scattered — the K threshold is over DISTINCT modules, not
    files, matching #10106's definition ("adds to K>=3 DISTINCT modules").
    """
    known_modules = {node.name for node in module_graph.nodes}
    symbol_modules: dict[str, set[str]] = defaultdict(set)
    symbol_files: dict[str, set[str]] = defaultdict(set)
    unmapped: set[str] = set()

    for file_path, symbols in added_symbols_by_file.items():
        if not symbols:
            continue
        module = _module_for_file(file_path, known_modules)
        for symbol in symbols:
            symbol_files[symbol].add(file_path)
            if module is None:
                unmapped.add(file_path)
            else:
                symbol_modules[symbol].add(module)

    scattered = tuple(
        ScatteredSymbol(
            symbol=symbol,
            modules=tuple(sorted(symbol_modules[symbol])),
            files=tuple(sorted(symbol_files[symbol])),
        )
        for symbol in sorted(symbol_modules)
        if len(symbol_modules[symbol]) >= threshold
    )
    return ScatterFinding(
        scattered=scattered,
        threshold=threshold,
        unmapped_files=tuple(sorted(unmapped)),
    )


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _symbol_in_added_line(line: str) -> str | None:
    for pattern in (_DEF_RE, _CLASS_RE, _CONST_RE):
        match = pattern.match(line)
        if match:
            name = match.group(1)
            return None if _is_dunder(name) else name
    return None


def added_symbols_for_range(
    repo_root: Path, commit_range: str
) -> dict[str, list[str]] | None:
    """Thin git+regex adapter: newly-added def/class/CONSTANT names per changed `.py` file.

    NOT part of the pure sensor; `compute` never calls this itself, and it
    has side effects (shells out) by design. Runs `git diff -U0` (zero
    context lines, so only genuinely added/removed lines appear) restricted
    to `*.py`, then applies `_symbol_in_added_line` to each `+` line.
    Mirrors `erosion.spread.changed_files_for_range`'s subprocess-timeout
    convention and its ``None``-on-any-git-failure contract, so callers can
    distinguish "no symbols added" (``{}``) from "couldn't determine
    changes" (``None``).
    """
    try:
        result = subprocess.run(
            ["git", "diff", "-U0", "--no-color", commit_range, "--", "*.py"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_READONLY_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    added_symbols: dict[str, list[str]] = {}
    current_file: str | None = None
    for line in result.stdout.splitlines():
        header = _DIFF_NEW_FILE_HEADER_RE.match(line)
        if header:
            current_file = header.group(1)
            continue
        if current_file is None or not line.startswith("+") or line.startswith("+++"):
            continue
        symbol = _symbol_in_added_line(line[1:])
        if symbol is None:
            continue
        file_symbols = added_symbols.setdefault(current_file, [])
        if symbol not in file_symbols:
            file_symbols.append(symbol)
    return added_symbols
