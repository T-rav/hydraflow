"""Only ``BeadsManager`` may write the worktree task store.

HydraFlow keeps phase-task state in each implementation worktree's
``.beads/issues.jsonl``, and ``BeadsManager`` owns every create, claim and
close under a bounded file lock. Per-worktree JSONL is what keeps concurrent
factory runs isolated, and the lock is what keeps a run internally consistent
— both are lost the moment a second writer appears, whether that is an agent
shelling out to a task CLI, a loop editing the file directly, or a helper
that "just appends one line".

The rule held when this guard was written: the only other modules that name
the file READ it (``fake_llm`` captures bytes at the persistence boundary)
or EXCLUDE it (``agent/_commit`` keeps task-store-only commits from counting
as delivery). This pins that, so a future writer has to argue for itself
rather than arrive unnoticed.

Source: docs/wiki/memory-feedback/feedback-beads-workflow.md
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

#: The module that owns the store. Adding a name here is the reviewable act.
_OWNERS = {"beads_manager.py"}

#: Writes we recognise. Reads (`read_text`, `read_bytes`, `open(...)` with no
#: mode or an "r" mode) are deliberately absent — this guard is about who
#: MUTATES the store, not who looks at it.
_WRITE_CALLS = {"write_text", "write_bytes", "append_jsonl", "unlink", "replace"}
_WRITE_MODES = re.compile(r"""["'][wax]\+?b?["']""")

#: How the store is named. Both spellings appear in the codebase.
_STORE_RE = re.compile(r"issues\.jsonl")


def _writes_the_store(source: str) -> list[str]:
    """Return descriptions of store-write sites in *source*."""
    if not _STORE_RE.search(source):
        return []
    tree = ast.parse(source)
    lines = source.splitlines()
    found: list[str] = []

    def names_store(lineno: int) -> bool:
        # The path is often built a line or two above the call.
        window = "\n".join(lines[max(0, lineno - 4) : lineno + 1])
        return bool(_STORE_RE.search(window))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = getattr(node.func, "attr", None)
        name = getattr(node.func, "id", None)
        if attr in _WRITE_CALLS or name in _WRITE_CALLS:
            if names_store(node.lineno):
                found.append(f"line {node.lineno}: {attr or name}()")
        elif name == "open":
            mode = next(
                (a for a in node.args[1:2] if isinstance(a, ast.Constant)), None
            )
            if (
                mode is not None
                and _WRITE_MODES.search(repr(mode.value))
                and names_store(node.lineno)
            ):
                found.append(f"line {node.lineno}: open(..., {mode.value!r})")
    return found


def test_only_the_manager_writes_the_task_store() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        if "node_modules" in path.parts or path.name in _OWNERS:
            continue
        sites = _writes_the_store(path.read_text(encoding="utf-8", errors="replace"))
        if sites:
            offenders[str(path.relative_to(_SRC))] = sites

    assert not offenders, (
        "Modules other than BeadsManager write .beads/issues.jsonl:\n"
        + "\n".join(f"  {f}: {', '.join(s)}" for f, s in offenders.items())
        + "\n\nPer-worktree JSONL under one lock is what keeps concurrent "
        "factory runs isolated. Route the mutation through BeadsManager, or "
        "add the module to _OWNERS with a reason a reviewer can weigh."
    )


def test_the_sweep_can_see_a_violation() -> None:
    """Anti-vacuity: the predicate must catch a known positive.

    Without this the guard passes for the wrong reason the moment the write
    verbs, the filename, or the proximity window stop matching how the code
    is written — a sweep that has quietly stopped seeing its subject looks
    exactly like a codebase with no violations.
    """
    planted = (
        "from pathlib import Path\n"
        "def rogue(worktree: Path) -> None:\n"
        "    store = worktree / '.beads' / 'issues.jsonl'\n"
        "    store.write_text('{}')\n"
    )
    assert _writes_the_store(planted), (
        "the predicate no longer recognises a direct write to the task store"
    )

    reader = (
        "from pathlib import Path\n"
        "def peek(worktree: Path) -> bytes:\n"
        "    store = worktree / '.beads' / 'issues.jsonl'\n"
        "    return store.read_bytes()\n"
    )
    assert not _writes_the_store(reader), (
        "the predicate flags a READ; it would fail the honest readers this "
        "guard deliberately allows"
    )
