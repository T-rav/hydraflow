"""Extract LabelStateMachine from the canonical transition declaration.

Looks for a top-level constant of the form
    TRANSITIONS = [(from_state, to_state, trigger?), ...]
(or `_TRANSITIONS` / `LABEL_TRANSITIONS`). Walks src/*.py until one is found.

HydraFlow's canonical source is `label_transitions.LABEL_TRANSITIONS` (the
single source of truth the runtime consults, ADR-0002 / issue #10621). This
extractor reads that literal verbatim so `docs/arch/generated/labels.md`
renders the real edge set, which the drift guard
`tests/architecture/test_label_state_matches_adr0002.py` diffs against the
Mermaid diagram in ADR-0002. If no declarative table is found the state
machine is empty (the pre-#10621 behavior).
"""

from __future__ import annotations

import ast
from pathlib import Path

from arch._models import LabelStateMachine, LabelTransition

_RECOGNIZED_NAMES = {"TRANSITIONS", "_TRANSITIONS", "LABEL_TRANSITIONS"}


def _target_name_and_value(
    node: ast.stmt,
) -> tuple[str, ast.expr] | None:
    """Return ``(name, value)`` for a top-level ``NAME = ...`` assignment.

    Handles both plain ``NAME = [...]`` (``ast.Assign``) and annotated
    ``NAME: T = [...]`` (``ast.AnnAssign``) so the canonical table can carry a
    type annotation. Returns ``None`` for anything else (bare annotations,
    tuple targets, augmented assignments, ...).
    """
    if isinstance(node, ast.Assign):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id, node.value
        return None
    if isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.value is not None:
            return node.target.id, node.value
        return None
    return None


def _literal_transitions(src_text: str) -> list[LabelTransition]:
    """Find a top-level TRANSITIONS = [...] of tuples and parse them."""
    try:
        tree = ast.parse(src_text)
    except SyntaxError:
        return []
    out: list[LabelTransition] = []
    for node in tree.body:
        target = _target_name_and_value(node)
        if target is None:
            continue
        name, value = target
        if name not in _RECOGNIZED_NAMES:
            continue
        if not isinstance(value, ast.List | ast.Tuple):
            continue
        for elt in value.elts:
            if not isinstance(elt, ast.Tuple):
                continue
            parts: list[str] = []
            for sub in elt.elts:
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    parts.append(sub.value)
                else:
                    break
            if len(parts) >= 2:
                out.append(
                    LabelTransition(
                        from_state=parts[0],
                        to_state=parts[1],
                        trigger=parts[2] if len(parts) > 2 else "",
                    )
                )
    return out


def extract_labels(src_dir: Path) -> LabelStateMachine:
    src_dir = Path(src_dir).resolve()
    transitions: list[LabelTransition] = []
    for py in sorted(src_dir.rglob("*.py")):
        try:
            text = py.read_text()
        except OSError:
            continue
        if not any(name in text for name in _RECOGNIZED_NAMES):
            continue
        transitions.extend(_literal_transitions(text))
        if transitions:
            break  # first hit wins; canonical source.

    states: set[str] = set()
    for t in transitions:
        states.add(t.from_state)
        states.add(t.to_state)
    transitions.sort(key=lambda t: (t.from_state, t.to_state, t.trigger))
    return LabelStateMachine(
        states=sorted(states),
        transitions=transitions,
    )
