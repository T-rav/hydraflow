"""Pure parsers for EventType ↔ reducer parity (no test logic, no IO except read).

See `docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md` §4.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# Accept either em-dash (—, U+2014) or ASCII hyphen (-) as the separator.
_BACKEND_ONLY_RE = re.compile(
    r"#\s*frontend:\s*backend-only(?:\s*[—-]\s*(?P<reason>.+?))?\s*$"
)
_MIN_REASON_LEN = 10


@dataclass(frozen=True)
class BackendOnlyEntry:
    value: str
    reason: str
    lineno: int


def parse_event_type_values(events_py: Path) -> set[str]:
    """Return all string values of the `EventType` enum in `events_py`."""
    tree = ast.parse(events_py.read_text(), filename=str(events_py))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == "EventType":
            return {v for v in (_string_value(c) for c in node.body) if v}
    msg = f"no `class EventType` found in {events_py}"
    raise ValueError(msg)


def _string_value(node: ast.stmt) -> str | None:
    if not isinstance(node, ast.Assign):
        return None
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return None
    if not isinstance(node.value, ast.Constant) or not isinstance(
        node.value.value, str
    ):
        return None
    return node.value.value


def parse_reducer_cases(jsx_path: Path) -> set[str]:
    """Return all `case '...':` literals from the JSX reducer file.

    Liberal regex match — picks up any `case 'foo':` or `case "foo":` in the file.
    """
    text = jsx_path.read_text()
    cases: set[str] = set()
    for match in re.finditer(r"case\s+['\"]([^'\"]+)['\"]\s*:", text):
        cases.add(match.group(1))
    return cases


def parse_backend_only_markers(events_py: Path) -> dict[str, BackendOnlyEntry]:
    """Return EventType members tagged `# frontend: backend-only — <reason>`.

    Members without a valid reason (missing dash, missing reason text, reason
    < _MIN_REASON_LEN chars) are NOT in the returned dict — they are
    treated as un-tagged (will fail parity if missing from reducer).

    Multi-line assignments (e.g. the formatter wrapped a long line into a
    parenthesised form) are handled by scanning every source line covered
    by the assignment node for the marker.
    """
    text = events_py.read_text()
    tree = ast.parse(text, filename=str(events_py))
    lines = text.splitlines()
    out: dict[str, BackendOnlyEntry] = {}
    enum_node = next(
        (
            n
            for n in ast.iter_child_nodes(tree)
            if isinstance(n, ast.ClassDef) and n.name == "EventType"
        ),
        None,
    )
    if enum_node is None:
        return out
    for child in enum_node.body:
        value = _string_value(child)
        if value is None:
            continue
        end_lineno = getattr(child, "end_lineno", child.lineno) or child.lineno
        match: re.Match[str] | None = None
        marker_lineno = child.lineno
        for line_no in range(child.lineno, end_lineno + 1):
            line_text = lines[line_no - 1]
            m = _BACKEND_ONLY_RE.search(line_text)
            if m is not None:
                match = m
                marker_lineno = line_no
                break
        if match is None:
            continue
        reason = (match.group("reason") or "").strip()
        if len(reason) < _MIN_REASON_LEN:
            continue
        out[value] = BackendOnlyEntry(value=value, reason=reason, lineno=marker_lineno)
    return out
