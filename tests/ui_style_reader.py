"""Shared JSX style-object reader for border shorthand/longhand regression pins.

Dashboard components define inline style objects as plain JS object literals
(no CSS-in-JS build step), so these regressions read `.jsx` source as text
rather than requiring the frontend toolchain. Used by
``tests/regressions/test_issue_10571.py`` and, once merged, the sibling
Header.jsx pin from issue #10564 — both need the same "does a style-object
family mix the ``border`` shorthand with its longhand sub-properties" check,
so the extraction + conflict logic lives here rather than being duplicated.

React warns when a style update removes a longhand sub-property
(``borderColor``/``borderWidth``/``borderStyle``) while the ``border``
shorthand remains set on the same node across a rerender ("mixing shorthand
and non-shorthand properties for the same value"). The fix is always the
same: express the base in longhand so variants only ever change a value,
never add/remove a key. ``borderRadius`` is a distinct CSS property (not a
``border`` sub-property) and must never be flagged.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Matches the bare `border` shorthand key only. `borderColor:`, `borderWidth:`,
# `borderStyle:`, `borderLeft:`, `borderRadius:`, etc. all have a non-colon,
# non-whitespace character immediately after "border", so they never match.
_BORDER_SHORTHAND_RE = re.compile(r"\bborder\s*:")
_BORDER_LONGHAND_KEYS = ("borderWidth", "borderStyle", "borderColor")


def read_source(path: Path) -> str:
    """Read a component source file, failing loudly if it's missing."""
    if not path.exists():
        msg = f"expected source file is missing: {path}"
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8")


def _extract_balanced_braces(src: str, open_brace_index: int) -> str:
    """Return the contents between the `{` at `open_brace_index` and its match."""
    if src[open_brace_index] != "{":
        msg = f"expected '{{' at index {open_brace_index}"
        raise AssertionError(msg)
    depth = 1
    cursor = open_brace_index + 1
    start = cursor
    while depth > 0:
        next_open = src.find("{", cursor)
        next_close = src.find("}", cursor)
        if next_close == -1:
            msg = "unbalanced braces: no matching '}' found"
            raise AssertionError(msg)
        if next_open != -1 and next_open < next_close:
            depth += 1
            cursor = next_open + 1
        else:
            depth -= 1
            cursor = next_close + 1
    return src[start : cursor - 1]


def extract_object_literal(src: str, name: str) -> str:
    """Return the balanced body of a top-level `name = { ... }` declaration.

    Matches `const NAME = {`, `let NAME = {`, `export const NAME = {`, or a
    bare `NAME = {` (property assigned after its containing object).
    """
    pattern = re.compile(rf"\b{re.escape(name)}\s*=\s*\{{")
    match = pattern.search(src)
    if not match:
        msg = f"could not locate {name!r} object literal"
        raise AssertionError(msg)
    return _extract_balanced_braces(src, match.end() - 1)


def extract_nested_object(container_src: str, key: str) -> str:
    """Return the balanced body of a `key: { ... }` entry within container_src."""
    pattern = re.compile(rf"\b{re.escape(key)}\s*:\s*\{{")
    match = pattern.search(container_src)
    if not match:
        msg = f"could not locate nested key {key!r} in container"
        raise AssertionError(msg)
    return _extract_balanced_braces(container_src, match.end() - 1)


def extract_spread_variants(src: str, base_name: str) -> list[str]:
    """Return every balanced `{ ...base_name, ... }` object literal in src."""
    variants = []
    pattern = re.compile(rf"\{{\s*\.\.\.{re.escape(base_name)}\b")
    for match in pattern.finditer(src):
        variants.append(_extract_balanced_braces(src, match.start()))
    return variants


def has_border_shorthand(obj_src: str) -> bool:
    """True if the object literal text defines the bare `border` shorthand key."""
    return bool(_BORDER_SHORTHAND_RE.search(obj_src))


def has_border_longhand(obj_src: str) -> bool:
    """True if the object literal text defines a border longhand sub-property."""
    return any(f"{key}:" in obj_src for key in _BORDER_LONGHAND_KEYS)


def find_border_shorthand_conflicts(
    label: str, base_src: str, variant_srcs: dict
) -> list[str]:
    """Return conflict descriptions for a base style object + its variants.

    A conflict is: `base_src` defines the `border` shorthand while a variant
    overrides a border longhand sub-property (without redefining `border`
    itself) — the exact "mixing shorthand and non-shorthand properties for
    the same value" hazard React warns about on rerender.
    """
    conflicts = []
    if has_border_shorthand(base_src):
        for variant_name, variant_src in variant_srcs.items():
            if has_border_longhand(variant_src) and not has_border_shorthand(
                variant_src
            ):
                conflicts.append(
                    f"{label}: base defines the `border` shorthand but variant "
                    f"{variant_name!r} overrides a border longhand sub-property "
                    "— convert the base to borderWidth/borderStyle/borderColor "
                    "longhand so variants only ever change a value"
                )
    return conflicts
