"""ADR touchpoint gate — P2 of the wiki-evolution audit.

Given a git diff (``--base`` vs ``--head``), reports Accepted ADRs
whose ``src/...`` citations intersect the changed files. The PR is
expected to either:

1. Include ADR updates in the diff (``docs/adr/*.md`` files touched).
2. Carry a ``Skip-ADR: <reason>`` marker in the PR body (checked by
   CI, not this script).

Without one of the escape hatches, the script exits non-zero so the
CI gate can fail the PR and surface which ADRs need attention.

Usage (CI):

    python scripts/check_adr_touchpoints.py \\
        --base origin/main --head HEAD

Usage (local):

    python scripts/check_adr_touchpoints.py --base main --head HEAD
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from adr_index import ADR, ADRIndex  # noqa: E402


def _changed_files(base: str, head: str) -> list[str]:
    """Return the list of files changed between *base* and *head*."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _file_at_rev(rev: str, path: str) -> str:
    """Return the contents of *path* at *rev*, or empty string if absent."""
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    return result.stdout if result.returncode == 0 else ""


def _file_symbols(source: str) -> dict[str, str] | None:
    """Return ``{qualified_name: source_text}`` for top-level + method
    symbols.  Returns ``None`` if *source* is not parseable Python — the
    caller should treat that as 'unknown, fire conservatively'."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out[node.name] = ast.unparse(node)
        elif isinstance(node, ast.ClassDef):
            out[node.name] = ast.unparse(node)
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    out[f"{node.name}.{child.name}"] = ast.unparse(child)
    return out


def _changed_symbols_in_file(before: str, after: str) -> set[str] | None:
    """Return the set of qualified symbols that differ between *before*
    and *after*.

    Returns ``None`` if either side fails to parse — callers must treat
    ``None`` as 'unknown' and fire the gate conservatively.  An empty
    set means 'no symbol-level changes' (e.g. only imports / module
    docstring / module-level constants changed)."""
    before_syms = _file_symbols(before)
    after_syms = _file_symbols(after)
    if before_syms is None or after_syms is None:
        return None
    changed: set[str] = set()
    for name, src in after_syms.items():
        if before_syms.get(name) != src:
            changed.add(name)
    for name in before_syms:
        if name not in after_syms:
            changed.add(name)
    return changed


def _changed_symbols_per_file(
    base: str, head: str, files: list[str]
) -> dict[str, set[str] | None]:
    """For each ``src/*.py`` file, return the set of changed symbols
    (or ``None`` if either revision can't be parsed)."""
    result: dict[str, set[str] | None] = {}
    for path in files:
        if not path.startswith("src/") or not path.endswith(".py"):
            continue
        before = _file_at_rev(base, path)
        after = _file_at_rev(head, path)
        result[path] = _changed_symbols_in_file(before, after)
    return result


_ADR_FILENAME_RE = re.compile(r"docs/adr/(\d{4})-[^/]+\.md$")


def _touched_adr_numbers(changed: list[str]) -> set[int]:
    """Return the numeric IDs of ADR markdown files present in the diff."""
    numbers: set[int] = set()
    for path in changed:
        m = _ADR_FILENAME_RE.search(path)
        if m:
            numbers.add(int(m.group(1)))
    return numbers


def _adr_fires_for_file(
    adr: ADR, file_path: str, changed_symbols: set[str] | None
) -> bool:
    """Decide whether *adr* should still fire for *file_path*.

    - Bare citation (empty symbol set) → fires on any change.
    - Symbol citation + ``changed_symbols is None`` → fires (unparseable diff).
    - Symbol citation + intersection with changed symbols → fires.
    - Symbol citation + no intersection → skipped.
    """
    cited_symbols = adr.source_symbols.get(file_path, frozenset())
    if not cited_symbols:
        # Bare citation — backwards-compatible "any change fires"
        return True
    if changed_symbols is None:
        # Unknown — be conservative
        return True
    for cited in cited_symbols:
        if cited in changed_symbols:
            return True
        # Class-level citation also fires on any of its method changes
        method_prefix = cited + "."
        if any(c.startswith(method_prefix) for c in changed_symbols):
            return True
    return False


def evaluate_gate(
    changed: list[str],
    hits: dict[str, list[ADR]],
    changed_symbols: dict[str, set[str] | None] | None = None,
) -> tuple[bool, dict[str, list[ADR]]]:
    """Pure decision function: does the diff clear the ADR gate?

    Returns ``(passed, unresolved_hits)``. A hit is **resolved** either
    by (1) updating one of the citing ADRs in the same diff, or (2) the
    diff not actually changing any of the symbols the ADR cites
    (symbol-level precision).  When *changed_symbols* is omitted, the
    gate falls back to the original file-level behavior — touching the
    file at all counts as a change.
    """
    if not hits:
        return True, {}
    touched_adrs = _touched_adr_numbers(changed)
    unresolved: dict[str, list[ADR]] = {}
    for path, adrs in hits.items():
        if any(a.number in touched_adrs for a in adrs):
            continue  # ADR updated in same PR — resolved
        symbols = changed_symbols.get(path) if changed_symbols is not None else None
        # When changed_symbols was supplied for this file, filter ADRs
        # whose cited symbols are unchanged.
        if changed_symbols is not None:
            still_firing = [a for a in adrs if _adr_fires_for_file(a, path, symbols)]
        else:
            still_firing = list(adrs)
        if still_firing:
            unresolved[path] = still_firing
    return (not unresolved), unresolved


def _format_report(hits: dict[str, list[ADR]]) -> str:
    lines = ["Accepted ADRs cite files touched in this PR:", ""]
    for path in sorted(hits):
        adrs = sorted(hits[path], key=lambda a: a.number)
        summaries = ", ".join(f"ADR-{a.number:04d} ({a.title})" for a in adrs)
        lines.append(f"  {path}")
        lines.append(f"    → {summaries}")
    lines.extend(
        [
            "",
            "Next steps:",
            "  - Update the relevant ADR(s) in the same PR, OR",
            "  - Add `Skip-ADR: <reason>` to the PR body (enforced by the",
            "    CI workflow — this script only reports touchpoints).",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Git base ref (e.g. origin/main)")
    parser.add_argument("--head", default="HEAD", help="Git head ref (default HEAD)")
    parser.add_argument(
        "--adr-dir",
        default=str(REPO_ROOT / "docs" / "adr"),
        help="ADR directory (default docs/adr)",
    )
    args = parser.parse_args()

    changed = _changed_files(args.base, args.head)
    if not changed:
        return 0

    idx = ADRIndex(Path(args.adr_dir))
    hits = idx.adrs_touching(changed)
    if not hits:
        return 0

    changed_symbols = _changed_symbols_per_file(args.base, args.head, changed)
    passed, unresolved = evaluate_gate(changed, hits, changed_symbols)
    if passed:
        print("Every touchpoint has a corresponding ADR update in this PR.")
        return 0

    print(_format_report(unresolved), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
