# Wiki Rot Detector Loop — §4.9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Land `WikiRotDetectorLoop` (spec §4.9) — a weekly `BaseBackgroundLoop` subclass that walks every `RepoWikiStore` repo (HydraFlow-self plus each managed repo), extracts cited code references via three complementary patterns (`path.py:symbol` / `src.dotted.path` / bare names inside fenced `python` blocks), **verifies cites via AST introspection** against HydraFlow-self's HEAD (grep fallback for markdown and for managed repos), emits a `difflib.get_close_matches` suggestion when a cite is broken, and files a `hydraflow-find` + `wiki-rot` issue per (slug, cite) miss through `PRManager.create_issue`. 3-attempt escalation to `hitl-escalation` + `wiki-rot-stuck`. Kill-switch via `LoopDeps.enabled_cb("wiki_rot_detector")` per spec §3.2 / §12.2 — **no `wiki_rot_detector_enabled` config field**.

**Architecture:** New `src/wiki_rot_detector_loop.py`; new helper `src/wiki_rot_citations.py` (cite extraction + AST verification + fuzzy match — factored out so unit tests exercise each without spinning up the loop); new state mixin `src/state/_wiki_rot_detector.py`; one config field (`wiki_rot_detector_interval`) + env override; five-checkpoint wiring; one MockWorld scenario + catalog builder. Dedup key format `f"wiki_rot_detector:{slug}:{cite}"`; per-cite attempt counters in `state.wiki_rot_attempts`.

**Spec refs:** `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §4.9, §3.2, §12.2.

**Sibling plan carries (locked from 2026-04-22-rc-budget-loop.md):**

1. Lazy-import `trace_collector.emit_loop_subprocess_trace` via `try/except ImportError` (caretaker-fleet Plan 6 owns it).
2. DedupStore clearance via `set_all(remaining)` — no `remove`/`discard` method (verified `src/dedup_store.py:55-65`).
3. Escalation key format `f"{worker_name}:{subject}"` → here `f"wiki_rot_detector:{slug}:{cite}"` (subject = `slug:cite` since a single broken cite identifies the work).
4. Threshold comparisons are `>=` (matches §3.2 "3 attempts" convention).
5. No `wiki_rot_detector_enabled` config field — kill-switch through `LoopDeps.enabled_cb("wiki_rot_detector")` only.

**Decisions locked (spec ambiguous or deferred):**

6. **Cite extraction regexes** (spec §4.9 bullet 2):
   - Style-A (house): `re.compile(r"\b([\w./-]+\.py):(\w+)")` — matches `src/foo.py:bar` / `tests/helpers/thing.py:Klass`.
   - Style-B (dotted): `re.compile(r"\b(src(?:\.\w+)+)\b")` — matches `src.repo_wiki.RepoWikiStore`. Last `.` splits module / symbol; symbol must be `[A-Za-z_][A-Za-z0-9_]*`.
   - Style-C (fenced hint): only within ```` ```python ... ``` ```` blocks, match bare identifiers that appear as `def foo(`, `class Foo`, or a trailing `foo(` call. Captured as **hints** (labelled `source="fenced_hint"`); excluded from the hard-cite verification pass but appended to issue bodies when near a broken hard cite for context.
7. **Verification target** = HydraFlow-self's `repo_root` (the HydraFlow repo checked out on the runner). For every other repo in `store.list_repos()` we have no source tree in-process, so the loop uses **grep-only** verification (open every `.md` under the wiki for a literal substring; if absent, assume broken). Managed-repo AST verification is **out of scope for v1** — noted as a follow-up in the loop docstring.
8. **AST verification** walks `FunctionDef` / `AsyncFunctionDef` / `ClassDef` nodes at any depth (nested classes and methods count). Re-exports via `from .foo import bar` resolve by opening the referenced module and re-running the walk once (depth-1 re-export resolution; deeper chains → grep fallback).
9. **Non-Python cite targets** (e.g. `.md`, `.json`, `.likec4`) skip AST and fall through to grep for the bare symbol inside the file. Missing file → broken cite.
10. **Fuzzy suggestion** via `difflib.get_close_matches(cite_symbol, module_symbols, n=1, cutoff=0.6)`. Only attempted for Style-A / Style-B hard cites whose **module file exists** but the symbol does not. Emits `Did you mean: {suggestion}?` in the issue body; absent when no close match clears the cutoff.
11. **Wiki entry loading** uses the public helper `RepoWikiStore.repo_dir(slug)` + `RepoWikiStore.load_topic_entries(path)` for each legacy-layout `*.md`, and for the Phase 3 per-entry layout, recurses into subdirectories and reads each file as raw markdown (we only need the prose + fenced blocks; no frontmatter parsing required for cite extraction). Missing `load_topic_entries` hits skip silently — the wiki may mix layouts during migration.
12. **Issue title format** = `f"Wiki rot: {entry_title} cites missing {cite}"` — this is the dedup match surface (`PRManager.create_issue` dedups on title).
13. **Excerpt** = first `≤500` chars of the entry body containing the broken cite; if the cite spans across >500 chars from the entry top, slide the window to center on it.
14. **History cap not required** — the loop does not accumulate past results in state; `wiki_rot_attempts` only holds live cite-subject → count, cleared on escalation close.
15. **Close-reconcile** polls `gh issue list --state closed --label hitl-escalation --label wiki-rot-stuck --author @me`; extracts the `slug:cite` suffix from each closed title (format `Wiki rot: ... cites missing <cite>` — we use the trailing token after `missing ` up to the first whitespace or end-of-line as the cite string, then re-prefix with the slug parsed from the issue body's first `Repo: ` line). Matches clear the dedup key and reset the attempt counter. Called at the top of each tick — no separate cron (spec §3.2).
16. **Tick cadence** matches interval — default `604800s` (weekly). Bounds `86400 – 2_592_000` (daily floor, monthly ceiling) in both `_INTERVAL_BOUNDS` and the config `Field(...)`.

---

## File Structure

| File | Role | C/M |
|---|---|---|
| `src/models.py:1757` | Append `wiki_rot_attempts: dict[str, int]` StateData field | M |
| `src/state/_wiki_rot_detector.py` | New `WikiRotDetectorStateMixin` — attempt getter/inc/clear | C |
| `src/state/__init__.py:28-45, 55-75` | Import mixin + append to `StateTracker` MRO | M |
| `src/config.py:174` | Append `wiki_rot_detector_interval` env-override row | M |
| `src/config.py:1619` | Append `wiki_rot_detector_interval` field after `retrospective_interval` | M |
| `src/wiki_rot_citations.py` | New helper — cite extraction regexes + AST verifier + fuzzy matcher | C |
| `src/wiki_rot_detector_loop.py` | New loop — per-repo tick + filing + escalation + reconcile | C |
| `src/service_registry.py:63, 168, 813, 871` | Import + dataclass field + constructor block + `ServiceRegistry(...)` kwarg | M |
| `src/orchestrator.py:158, 909` | `bg_loop_registry` entry + `loop_factories` tuple | M |
| `src/ui/src/constants.js:252, 273, 312` | `EDITABLE_INTERVAL_WORKERS` + `SYSTEM_WORKER_INTERVALS` + `BACKGROUND_WORKERS` entries | M |
| `src/dashboard_routes/_common.py:55` | `_INTERVAL_BOUNDS` entry | M |
| `tests/test_state_wiki_rot_detector.py` | Mixin unit tests | C |
| `tests/test_wiki_rot_citations.py` | Helper unit tests (regex + AST + fuzzy) | C |
| `tests/test_wiki_rot_detector_loop.py` | Loop unit tests (skeleton, warmup, filing, escalation, reconcile, kill-switch) | C |
| `tests/scenarios/catalog/loop_registrations.py:234` | `_build_wiki_rot_detector` + `_BUILDERS` entry | M |
| `tests/scenarios/catalog/test_loop_instantiation.py:34` | `"wiki_rot_detector",` | M |
| `tests/scenarios/catalog/test_loop_registrations.py:34` | `"wiki_rot_detector",` | M |
| `tests/scenarios/test_wiki_rot_detector_scenario.py` | MockWorld scenario — seed wiki + broken cite + assert filing | C |
| `tests/test_loop_wiring_completeness.py` | Regex auto-discovery — no edit required | Covered |

---

## Task 1 — State schema for per-cite repair attempts

**Modify** `src/models.py:1757` — after `code_grooming_filed: list[str] = Field(default_factory=list)`, insert:

```python
    # Trust fleet — WikiRotDetectorLoop (spec §4.9)
    wiki_rot_attempts: dict[str, int] = Field(default_factory=dict)
```

**Modify** `src/state/__init__.py:28-45` — add `from ._wiki_rot_detector import WikiRotDetectorStateMixin` in alphabetical position (after `TraceRunsMixin` import block — alphabetically `WikiRot` sorts after `TraceRuns`, `Worker`, `Workspace`; insert as the final mixin import).

**Modify** `src/state/__init__.py:55-75` — append `WikiRotDetectorStateMixin,` to the `StateTracker` MRO immediately before the closing `):`.

- [ ] **Step 1: Write failing mixin test** — `tests/test_state_wiki_rot_detector.py`:

```python
"""Tests for WikiRotDetectorStateMixin (spec §4.9)."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_get_returns_zero_when_unset(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_wiki_rot_attempts("hydra/hydraflow:src/foo.py:bar") == 0


def test_inc_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    key = "hydra/hydraflow:src/foo.py:bar"
    assert st.inc_wiki_rot_attempts(key) == 1
    assert st.inc_wiki_rot_attempts(key) == 2
    assert st.inc_wiki_rot_attempts(key) == 3
    assert st.get_wiki_rot_attempts("other:key") == 0


def test_clear_resets_single_key(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.inc_wiki_rot_attempts("a")
    st.inc_wiki_rot_attempts("b")
    st.clear_wiki_rot_attempts("a")
    assert st.get_wiki_rot_attempts("a") == 0
    assert st.get_wiki_rot_attempts("b") == 1


def test_persists_across_instances(tmp_path: Path) -> None:
    st1 = _tracker(tmp_path)
    st1.inc_wiki_rot_attempts("persist")
    st2 = _tracker(tmp_path)
    assert st2.get_wiki_rot_attempts("persist") == 1
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError`):

  ```bash
  PYTHONPATH=src uv run pytest tests/test_state_wiki_rot_detector.py -v
  ```

- [ ] **Step 3: Create** `src/state/_wiki_rot_detector.py`:

```python
"""State accessors for WikiRotDetectorLoop (spec §4.9).

Per-cite repair attempt counters. The key format is
``f"{slug}:{cite}"`` so that the same broken cite across two repos counts
independently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class WikiRotDetectorStateMixin:
    """Per-cite repair attempts for WikiRotDetectorLoop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_wiki_rot_attempts(self, key: str) -> int:
        return int(self._data.wiki_rot_attempts.get(key, 0))

    def inc_wiki_rot_attempts(self, key: str) -> int:
        current = int(self._data.wiki_rot_attempts.get(key, 0)) + 1
        attempts = dict(self._data.wiki_rot_attempts)
        attempts[key] = current
        self._data.wiki_rot_attempts = attempts
        self.save()
        return current

    def clear_wiki_rot_attempts(self, key: str) -> None:
        attempts = dict(self._data.wiki_rot_attempts)
        attempts.pop(key, None)
        self._data.wiki_rot_attempts = attempts
        self.save()
```

- [ ] **Step 4: Apply models.py + state/__init__.py edits (above).**
- [ ] **Step 5: Re-run — expect 4 PASS.**
- [ ] **Step 6: Commit:**

  ```bash
  git add src/models.py src/state/_wiki_rot_detector.py src/state/__init__.py tests/test_state_wiki_rot_detector.py
  git commit -m "feat(state): WikiRotDetectorStateMixin + wiki_rot_attempts field (§4.9)"
  ```

---

## Task 2 — Config field + env override

**Modify** `src/config.py:1619` — after `retrospective_interval`'s closing `)` (and after any sibling plan's additions), insert:

```python
    # Trust fleet — WikiRotDetectorLoop (spec §4.9)
    wiki_rot_detector_interval: int = Field(
        default=604800, ge=86400, le=2_592_000,
        description="Seconds between WikiRotDetectorLoop ticks (default 7d)",
    )
```

**Modify** `src/config.py:174` (`_ENV_INT_OVERRIDES`) — append:

```python
    ("wiki_rot_detector_interval", "HYDRAFLOW_WIKI_ROT_DETECTOR_INTERVAL", 604800),
```

- [ ] **Step 1: Write failing test** — append to an existing config test module or create `tests/test_config_wiki_rot_detector.py`:

```python
"""Tests for WikiRotDetectorLoop config fields (spec §4.9)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from config import HydraFlowConfig


def test_wiki_rot_detector_default() -> None:
    cfg = HydraFlowConfig()
    assert cfg.wiki_rot_detector_interval == 604800


def test_wiki_rot_detector_env_override() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_WIKI_ROT_DETECTOR_INTERVAL": "86400"}):
        assert HydraFlowConfig.from_env().wiki_rot_detector_interval == 86400


def test_wiki_rot_detector_interval_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(wiki_rot_detector_interval=30)
    with pytest.raises(ValueError):
        HydraFlowConfig(wiki_rot_detector_interval=10_000_000)
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Apply config.py edits (above).**
- [ ] **Step 4: Re-run — expect 3 PASS.**
- [ ] **Step 5: Commit:**

  ```bash
  git add src/config.py tests/test_config_wiki_rot_detector.py
  git commit -m "feat(config): wiki_rot_detector_interval + env override (§4.9)"
  ```

---

## Task 3 — Cite-extraction helper

This is the first of three helper concerns factored into `src/wiki_rot_citations.py`. Keeping extraction, AST verification, and fuzzy matching in one helper module (but separate functions) keeps the loop thin and makes each regex / AST branch individually unit-testable.

- [ ] **Step 1: Write failing tests** — create `tests/test_wiki_rot_citations.py`:

```python
"""Tests for wiki_rot_citations helpers (spec §4.9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_rot_citations import (
    Cite,
    extract_cites,
    extract_fenced_hints,
    fuzzy_suggest,
    verify_cite_ast,
    verify_cite_grep,
)


def test_extract_cites_style_a_house() -> None:
    text = "See src/foo.py:bar and tests/helpers/thing.py:Klass."
    got = [(c.module, c.symbol, c.style) for c in extract_cites(text)]
    assert ("src/foo.py", "bar", "colon") in got
    assert ("tests/helpers/thing.py", "Klass", "colon") in got


def test_extract_cites_style_b_dotted() -> None:
    text = "The guard lives in src.repo_wiki.RepoWikiStore."
    got = [(c.module, c.symbol, c.style) for c in extract_cites(text)]
    assert ("src.repo_wiki", "RepoWikiStore", "dotted") in got


def test_extract_cites_does_not_match_dotted_outside_src() -> None:
    # Style-B is anchored to the ``src`` root to avoid over-matching
    # ordinary prose like "the big.bad.wolf".
    assert extract_cites("the big.bad.wolf") == []


def test_extract_cites_dedupes_identical_citations() -> None:
    text = "src/foo.py:bar once. src/foo.py:bar twice."
    got = extract_cites(text)
    assert len(got) == 1


def test_extract_fenced_hints_only_inside_python_blocks() -> None:
    md = (
        "regular prose mentioning foo(\n\n"
        "```python\n"
        "def outer_helper(x): ...\n"
        "class InnerThing: pass\n"
        "outer_helper(1)\n"
        "```\n\n"
        "```\n"
        "def not_a_hint(): ...\n"
        "```\n"
    )
    hints = {h.symbol for h in extract_fenced_hints(md)}
    assert "outer_helper" in hints
    assert "InnerThing" in hints
    assert "not_a_hint" not in hints  # outside a ``python`` fence


def test_verify_cite_ast_present(tmp_path: Path) -> None:
    mod = tmp_path / "src" / "foo.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("def bar():\n    return 1\n\nclass Baz:\n    pass\n")
    ok, symbols = verify_cite_ast(tmp_path, "src/foo.py", "bar")
    assert ok
    assert "bar" in symbols
    assert "Baz" in symbols


def test_verify_cite_ast_missing_symbol(tmp_path: Path) -> None:
    mod = tmp_path / "src" / "foo.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("def other(): ...\n")
    ok, symbols = verify_cite_ast(tmp_path, "src/foo.py", "bar")
    assert not ok
    assert symbols == ["other"]


def test_verify_cite_ast_handles_reexport_depth_1(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "_impl.py").write_text("def bar(): ...\n")
    (pkg / "__init__.py").write_text("from ._impl import bar\n")
    ok, _ = verify_cite_ast(tmp_path, "src/pkg/__init__.py", "bar")
    assert ok


def test_verify_cite_ast_missing_module_returns_false(tmp_path: Path) -> None:
    ok, symbols = verify_cite_ast(tmp_path, "src/does_not_exist.py", "bar")
    assert not ok
    assert symbols == []


def test_verify_cite_ast_dotted_style(tmp_path: Path) -> None:
    mod = tmp_path / "src" / "foo.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("class Guard: pass\n")
    cite = Cite(module="src.foo", symbol="Guard", style="dotted", raw="src.foo.Guard")
    ok, _ = verify_cite_ast(tmp_path, cite.module_as_path(), cite.symbol)
    assert ok


def test_verify_cite_grep_hit_and_miss(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "adr" / "0001.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("See FooBar for details.\n")
    assert verify_cite_grep(tmp_path, "docs/adr/0001.md", "FooBar")
    assert not verify_cite_grep(tmp_path, "docs/adr/0001.md", "Missing")
    # Missing file → False, not exception.
    assert not verify_cite_grep(tmp_path, "does/not/exist.md", "anything")


def test_fuzzy_suggest_close_match() -> None:
    assert fuzzy_suggest("bar", ["baz", "barr", "quux"]) == "barr"


def test_fuzzy_suggest_no_match() -> None:
    assert fuzzy_suggest("zzzzzz", ["alpha", "beta"]) is None
```

- [ ] **Step 2: Run — expect FAIL (`ImportError`):**

  ```bash
  PYTHONPATH=src uv run pytest tests/test_wiki_rot_citations.py -v
  ```

- [ ] **Step 3: Create** `src/wiki_rot_citations.py`:

```python
"""Citation extraction + AST verification + fuzzy suggestion for
:mod:`wiki_rot_detector_loop` (spec §4.9).

Three extraction patterns, one AST verifier, one grep fallback, one
fuzzy matcher. Each function is side-effect-free and unit-testable in
isolation — the loop composes them per cite.
"""

from __future__ import annotations

import ast
import difflib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hydraflow.wiki_rot_citations")

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Style-A: ``path/to/module.py:symbol`` — the HydraFlow house style.
_STYLE_A_RE = re.compile(r"\b([\w./-]+\.py):(\w+)")

# Style-B: ``src.module.Class`` — dotted Python import path anchored to
# the ``src`` root. Anchoring to ``src`` prevents false positives on
# ordinary dotted prose (``big.bad.wolf``). The final segment is the
# symbol; everything before is the module dotted path.
_STYLE_B_RE = re.compile(r"\b(src(?:\.\w+)+)\b")

# Style-C: bare identifiers within ``` ```python ``` ``` fences that look
# like cites (def / class / call sites). Hints only — ambiguous without
# context.
_FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*[:(]", re.MULTILINE)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True)
class Cite:
    """A single cite candidate extracted from a wiki entry.

    ``module`` is either a slashed file path (Style-A) or a dotted Python
    path (Style-B / C).  ``style`` indicates which extractor produced it.
    ``raw`` is the verbatim substring for display in issue bodies.
    """

    module: str
    symbol: str
    style: str  # "colon" | "dotted" | "fenced_hint"
    raw: str

    def module_as_path(self) -> str:
        """Return ``module`` normalised to a slashed ``.py`` path.

        Style-A is already slashed; Style-B is dotted (``src.foo.bar``
        → ``src/foo/bar.py``); Style-C (fence hint) has no module path
        and returns an empty string — callers must skip AST verification
        for hints.
        """
        if self.style == "colon":
            return self.module
        if self.style == "dotted":
            return self.module.replace(".", "/") + ".py"
        return ""


def extract_cites(text: str) -> list[Cite]:
    """Extract Style-A + Style-B hard cites from arbitrary markdown/prose.

    Deduplicated by ``(module, symbol, style)``.  Fenced-code hints
    (Style-C) are **excluded** — see :func:`extract_fenced_hints`.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[Cite] = []

    for m in _STYLE_A_RE.finditer(text):
        key = (m.group(1), m.group(2), "colon")
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Cite(module=m.group(1), symbol=m.group(2), style="colon", raw=m.group(0))
        )

    for m in _STYLE_B_RE.finditer(text):
        path = m.group(1)
        parts = path.split(".")
        if len(parts) < 2:
            continue
        module = ".".join(parts[:-1])
        symbol = parts[-1]
        # Only treat the last segment as a symbol if it starts with an
        # identifier char — some prose ends in ``src.foo.`` (trailing dot)
        # which the `\b` anchor does not catch.
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", symbol):
            continue
        key = (module, symbol, "dotted")
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Cite(module=module, symbol=symbol, style="dotted", raw=path)
        )

    return out


def extract_fenced_hints(text: str) -> list[Cite]:
    """Return Style-C fenced-code hints — bare symbol names inside
    ``` ```python ``` ``` fences.

    Emitted as :class:`Cite` with ``style="fenced_hint"`` and an empty
    ``module`` field.  Callers use these as contextual appendices only;
    they are not verified against the filesystem.
    """
    seen: set[str] = set()
    out: list[Cite] = []

    for fence in _FENCE_RE.finditer(text):
        body = fence.group(1)
        for rx in (_DEF_RE, _CLASS_RE, _CALL_RE):
            for sym_match in rx.finditer(body):
                name = sym_match.group(1)
                if name in seen or name in _BUILTINS_DENY:
                    continue
                seen.add(name)
                out.append(
                    Cite(module="", symbol=name, style="fenced_hint", raw=name)
                )

    return out


# Python builtins and common stdlib names that pollute fenced-hint
# extraction. Suppressed so the issue context doesn't list ``print``,
# ``len`` and friends as "hints".
_BUILTINS_DENY: frozenset[str] = frozenset(
    {
        "print", "len", "list", "dict", "set", "tuple", "str", "int",
        "float", "bool", "range", "enumerate", "zip", "open", "isinstance",
        "type", "hasattr", "getattr", "setattr", "repr", "id", "map",
        "filter", "sorted", "reversed", "sum", "min", "max", "abs", "any",
        "all", "iter", "next", "self", "cls", "True", "False", "None",
    }
)


# ---------------------------------------------------------------------------
# AST verification
# ---------------------------------------------------------------------------


def verify_cite_ast(
    repo_root: Path, module_path: str, symbol: str
) -> tuple[bool, list[str]]:
    """Verify *symbol* exists in *module_path* via AST walk.

    Returns ``(ok, symbols)`` where ``symbols`` is the sorted list of
    defined `FunctionDef` / `AsyncFunctionDef` / `ClassDef` names
    (useful for fuzzy suggestions).  For ``__init__.py`` re-exports
    (``from .x import y``), the verifier opens the referenced module
    once and rescans — depth-1 only; deeper chains fall back to grep.

    Non-Python paths, missing files, and parse errors all return
    ``(False, [])`` — callers treat them as broken cites or route them
    to :func:`verify_cite_grep`.
    """
    if not module_path.endswith(".py"):
        return False, []

    module_file = repo_root / module_path
    if not module_file.is_file():
        return False, []

    try:
        tree = ast.parse(module_file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        logger.debug("AST parse failed for %s", module_file, exc_info=True)
        return False, []

    symbols = _collect_defined_symbols(tree)

    if symbol in symbols:
        return True, sorted(symbols)

    # Depth-1 re-export resolution: scan ``from .foo import bar`` lines.
    reexport_hits = _follow_reexports(tree, module_file, symbol)
    if reexport_hits:
        return True, sorted(symbols | reexport_hits)

    return False, sorted(symbols)


def _collect_defined_symbols(tree: ast.AST) -> set[str]:
    """Walk *tree* for top-level + nested defs and return symbol names."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            out.add(node.name)
    return out


def _follow_reexports(
    tree: ast.AST, module_file: Path, symbol: str
) -> set[str]:
    """Resolve ``from .x import *`` / ``from .x import symbol`` one level.

    Returns the set of symbols defined in the *re-exported* module if
    that module defines *symbol*; otherwise an empty set.  Deeper chains
    are intentionally not followed — grep fallback covers those.
    """
    module_dir = module_file.parent
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module is None or node.level == 0:
            continue
        target_parts = node.module.split(".")
        target_file = module_dir.joinpath(*target_parts).with_suffix(".py")
        if not target_file.is_file():
            target_file = module_dir.joinpath(*target_parts, "__init__.py")
            if not target_file.is_file():
                continue
        try:
            sub_tree = ast.parse(target_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        sub_syms = _collect_defined_symbols(sub_tree)
        imported = {a.name for a in node.names}
        if symbol in sub_syms and (symbol in imported or "*" in imported):
            return sub_syms
    return set()


# ---------------------------------------------------------------------------
# Grep fallback (non-Python cites + managed-repo mirrors)
# ---------------------------------------------------------------------------


def verify_cite_grep(
    repo_root: Path, file_path: str, needle: str
) -> bool:
    """Substring search fallback for ``.md`` / ``.json`` / managed-repo
    targets.  ``True`` iff *needle* appears in the file at
    ``repo_root / file_path``.  Missing file → ``False``.
    """
    target = repo_root / file_path
    if not target.is_file():
        return False
    try:
        return needle in target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Fuzzy suggestion
# ---------------------------------------------------------------------------


def fuzzy_suggest(symbol: str, candidates: list[str]) -> str | None:
    """Return the closest match to *symbol* from *candidates* or ``None``.

    Cutoff `0.6` — the `difflib` default — is loose enough to catch
    plausible typo/rename drift (``foo_bar`` → ``foo_baz``) without
    drowning operators in spurious suggestions.
    """
    matches = difflib.get_close_matches(symbol, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None
```

- [ ] **Step 4: Re-run — expect all 12 PASS.**

- [ ] **Step 5: Commit:**

  ```bash
  git add src/wiki_rot_citations.py tests/test_wiki_rot_citations.py
  git commit -m "feat(wiki-rot): citation extraction + AST verification + fuzzy matcher (§4.9)"
  ```

---

## Task 4 — Loop skeleton + per-repo tick stub

- [ ] **Step 1: Write failing test** — `tests/test_wiki_rot_detector_loop.py`:

```python
"""Tests for WikiRotDetectorLoop (spec §4.9)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from wiki_rot_detector_loop import WikiRotDetectorLoop


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(), stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_wiki_rot_attempts.return_value = 0
    state.inc_wiki_rot_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    wiki_store = MagicMock()
    wiki_store.list_repos.return_value = []
    return cfg, state, pr_manager, dedup, wiki_store


def _loop(env, *, enabled: bool = True) -> WikiRotDetectorLoop:
    cfg, state, pr, dedup, wiki_store = env
    return WikiRotDetectorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup,
        wiki_store=wiki_store, deps=_deps(asyncio.Event(), enabled=enabled),
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "wiki_rot_detector"
    assert loop._get_default_interval() == 604800


async def test_do_work_noop_when_no_repos(loop_env) -> None:
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "noop"
    assert stats["repos_scanned"] == 0
    _, _, pr, _, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_do_work_disabled_short_circuits(loop_env) -> None:
    loop = _loop(loop_env, enabled=False)
    # The base class short-circuits `run`, not `_do_work`; we test the
    # explicit kill-switch guard at the top of `_do_work`.
    stats = await loop._do_work()
    assert stats["status"] == "disabled"
```

- [ ] **Step 2: Run — expect FAIL (`ImportError`):**

  ```bash
  PYTHONPATH=src uv run pytest tests/test_wiki_rot_detector_loop.py -v
  ```

- [ ] **Step 3: Create** `src/wiki_rot_detector_loop.py`:

```python
"""WikiRotDetectorLoop — weekly wiki cite freshness detector (spec §4.9).

Walks every ``RepoWikiStore``-registered repo, extracts cited code
references from each wiki entry via three patterns (``path.py:symbol``,
dotted ``src.module.Class``, and bare identifiers inside ``python``
fences — hints only), and verifies each hard cite against:

- **HydraFlow-self** (``config.repo_root``) via AST introspection —
  catches re-exports and ``__init__.py`` re-bindings that grep misses.
- **Managed repos** via grep over wiki markdown mirrors only — full
  AST verification across every managed repo is out of scope for v1
  and noted below as a follow-up.

For each broken cite the loop files a ``hydraflow-find`` + ``wiki-rot``
issue through :class:`PRManager` with a fuzzy-match suggestion (via
:func:`difflib.get_close_matches`) when the containing module exists.
After 3 unresolved attempts per ``(slug, cite)`` subject the loop
escalates to ``hitl-escalation`` + ``wiki-rot-stuck``. Dedup keys and
attempt counters clear on escalation close per spec §3.2.

Kill-switch: :meth:`LoopDeps.enabled_cb` with ``worker_name="wiki_rot_detector"``
— **no ``wiki_rot_detector_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult
from wiki_rot_citations import (
    Cite,
    extract_cites,
    extract_fenced_hints,
    fuzzy_suggest,
    verify_cite_ast,
    verify_cite_grep,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from repo_wiki import RepoWikiStore
    from state import StateTracker

logger = logging.getLogger("hydraflow.wiki_rot_detector_loop")

_MAX_ATTEMPTS = 3
_EXCERPT_CHARS = 500
_ISSUE_LABELS_FIND: tuple[str, ...] = ("hydraflow-find", "wiki-rot")
_ISSUE_LABELS_ESCALATE: tuple[str, ...] = ("hitl-escalation", "wiki-rot-stuck")


class WikiRotDetectorLoop(BaseBackgroundLoop):
    """Detects broken code cites in per-repo wikis (spec §4.9)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        wiki_store: RepoWikiStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="wiki_rot_detector", config=config, deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._wiki = wiki_store

    def _get_default_interval(self) -> int:
        return self._config.wiki_rot_detector_interval

    # -- main tick ---------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """Scan every repo wiki, file an issue per broken cite, escalate
        repeat offenders.  Guarded by the kill-switch at the top so a
        mid-tick flip takes effect on the next cycle.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        await self._reconcile_closed_escalations()

        self_slug = self._config.repo or ""
        repos = list(self._wiki.list_repos())
        if self_slug and self_slug not in repos:
            # Ensure we always scan HydraFlow-self even if its wiki has
            # not been seeded yet (cite extraction will just yield 0).
            repos.insert(0, self_slug)

        scanned = 0
        filed = 0
        escalated = 0
        for slug in repos:
            try:
                result = await self._tick_repo(slug, self_slug)
            except Exception:  # noqa: BLE001
                logger.exception("wiki_rot_detector: slug=%s failed", slug)
                continue
            scanned += 1
            filed += result["filed"]
            escalated += result["escalated"]

        status = "fired" if filed or escalated else "noop"
        return {
            "status": status,
            "repos_scanned": scanned,
            "issues_filed": filed,
            "escalations": escalated,
        }

    async def _tick_repo(
        self, slug: str, self_slug: str,
    ) -> dict[str, int]:
        """Task 5."""
        return {"filed": 0, "escalated": 0}

    async def _reconcile_closed_escalations(self) -> None:
        """Task 6."""
        return None
```

- [ ] **Step 4: Re-run — expect 3 PASS.**
- [ ] **Step 5: Commit:**

  ```bash
  git add src/wiki_rot_detector_loop.py tests/test_wiki_rot_detector_loop.py
  git commit -m "feat(loop): WikiRotDetectorLoop skeleton + per-repo tick stub (§4.9)"
  ```

---

## Task 5 — Per-repo tick: load wiki, extract cites, verify, file issues, escalate

- [ ] **Step 1: Append failing tests** to `tests/test_wiki_rot_detector_loop.py`:

```python
async def test_tick_repo_files_issue_on_broken_cite(
    tmp_path: Path, loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    # Seed a minimal wiki directory with one entry that cites a missing
    # symbol in a module that *does* exist.
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    entry = wiki_dir / "patterns.md"
    entry.write_text(
        "# Patterns\n\n## Entry A\n\n"
        "The guard lives in src/foo.py:bar — see ADR-0099.\n"
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]

    # Seed HydraFlow-self source so AST verification resolves to a real
    # module without the missing symbol.
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "foo.py").write_text("def other():\n    return 1\n")
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 1, stats
    pr.create_issue.assert_awaited_once()
    title, body, labels = pr.create_issue.await_args.args
    assert "Wiki rot" in title
    assert "src/foo.py:bar" in title
    assert "Did you mean: other" in body
    assert set(labels) == {"hydraflow-find", "wiki-rot"}


async def test_tick_repo_dedups_repeat_cite(
    tmp_path: Path, loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    dedup.get.return_value = {f"wiki_rot_detector:{slug}:src/foo.py:bar"}
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "patterns.md").write_text("src/foo.py:bar\n")
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_tick_repo_escalates_on_third_attempt(
    tmp_path: Path, loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    # Not already deduped — simulate "new" fire but 3rd attempt counter.
    dedup.get.return_value = set()
    state.get_wiki_rot_attempts.return_value = 2
    state.inc_wiki_rot_attempts.return_value = 3

    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "patterns.md").write_text("src/foo.py:bar\n")
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["escalations"] == 1, stats
    assert stats["issues_filed"] == 1  # filed + escalated in same tick
    # Two create_issue calls: the find and the escalation.
    calls = pr.create_issue.await_args_list
    assert len(calls) == 2
    labels_escalate = calls[-1].args[2]
    assert set(labels_escalate) == {"hitl-escalation", "wiki-rot-stuck"}
```

- [ ] **Step 2: Run — expect FAIL** (stub returns zeroes).

- [ ] **Step 3: Replace the `_tick_repo` stub** in `src/wiki_rot_detector_loop.py` with the full implementation (append near the end of the class):

```python
    async def _tick_repo(
        self, slug: str, self_slug: str,
    ) -> dict[str, int]:
        """Scan one repo's wiki entries, verify cites, file issues, and
        escalate repeat offenders.

        Returns counts ``{"filed": n, "escalated": n}``.  Failures on
        a single entry are logged and skipped — the tick never aborts
        mid-repo.
        """
        filed = 0
        escalated = 0

        entries = self._load_wiki_entries(slug)
        if not entries:
            return {"filed": 0, "escalated": 0}

        is_self = slug == self_slug and bool(self_slug)
        repo_root = Path(self._config.repo_root)
        dedup_seen = self._dedup.get()

        for title, body, entry_path in entries:
            cites = extract_cites(body)
            hints = extract_fenced_hints(body)
            for cite in cites:
                broken, suggestion = self._check_cite(cite, repo_root, is_self)
                if not broken:
                    continue
                subject = f"{slug}:{cite.raw}"
                dedup_key = f"wiki_rot_detector:{subject}"
                if dedup_key in dedup_seen:
                    continue

                filed += 1
                await self._file_find(
                    slug=slug,
                    entry_title=title,
                    entry_path=str(entry_path),
                    body=body,
                    cite=cite,
                    suggestion=suggestion,
                    hints=hints,
                )
                dedup_seen.add(dedup_key)

                attempts = self._state.inc_wiki_rot_attempts(subject)
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(
                        slug=slug, cite=cite, attempts=attempts,
                    )
                    escalated += 1

        self._dedup.set_all(dedup_seen)
        return {"filed": filed, "escalated": escalated}

    # -- helpers -----------------------------------------------------------

    def _load_wiki_entries(
        self, slug: str,
    ) -> list[tuple[str, str, Path]]:
        """Return ``[(title, body, path), ...]`` for every markdown entry
        in the repo's wiki — supports both the legacy topic-file layout
        and the Phase 3 per-entry layout.  Title defaults to the file
        stem when no ``# Heading`` is present.
        """
        try:
            repo_dir = self._wiki.repo_dir(slug)
        except Exception:  # noqa: BLE001
            logger.debug("wiki.repo_dir(%s) failed", slug, exc_info=True)
            return []
        if not repo_dir.is_dir():
            return []

        out: list[tuple[str, str, Path]] = []
        for md_path in sorted(repo_dir.rglob("*.md")):
            if md_path.name in {"index.md", "log.md"}:
                continue
            try:
                text = md_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = _first_heading(text) or md_path.stem
            out.append((title, text, md_path))
        return out

    def _check_cite(
        self, cite: Cite, repo_root: Path, is_self: bool,
    ) -> tuple[bool, str | None]:
        """Verify *cite* and emit a fuzzy suggestion when plausible.

        Returns ``(broken, suggestion)``.  ``broken`` is ``True`` when
        the cite does not resolve; ``suggestion`` is a close-match
        symbol name from the same module, or ``None`` when no close
        match exists / the module itself is missing.
        """
        if cite.style == "fenced_hint":
            return (False, None)  # hints never trigger fires

        module_path = cite.module_as_path()

        if is_self:
            ok, symbols = verify_cite_ast(repo_root, module_path, cite.symbol)
            if ok:
                return (False, None)
            suggestion = fuzzy_suggest(cite.symbol, symbols) if symbols else None
            return (True, suggestion)

        # Managed repo — grep wiki markdown mirrors only (AST verification
        # against unchecked-out managed-repo sources is out of scope v1).
        ok = verify_cite_grep(repo_root, module_path, cite.symbol)
        return (not ok, None)

    async def _file_find(
        self,
        *,
        slug: str,
        entry_title: str,
        entry_path: str,
        body: str,
        cite: Cite,
        suggestion: str | None,
        hints: list[Cite],
    ) -> None:
        title = f"Wiki rot: {entry_title} cites missing {cite.raw}"
        excerpt = _excerpt_around(body, cite.raw, _EXCERPT_CHARS)
        lines: list[str] = [
            "**Automated detection — WikiRotDetectorLoop (spec §4.9).**",
            "",
            f"- Repo: `{slug}`",
            f"- Entry: `{entry_path}` — *{entry_title}*",
            f"- Broken cite: `{cite.raw}` ({cite.style})",
        ]
        if suggestion:
            lines.append(f"- Did you mean: `{suggestion}`?")
        if hints:
            hint_names = ", ".join(sorted({h.symbol for h in hints})[:10])
            lines.append(f"- Fenced-code hints (context only): {hint_names}")
        lines += [
            "",
            "### Entry excerpt",
            "",
            "```markdown",
            excerpt,
            "```",
            "",
            "Repair path: implementer updates the cite or removes the "
            "stale entry; the caretaker wiki loop compiles the patch "
            "through the standard review + auto-merge flow.",
        ]
        body_out = "\n".join(lines)
        await self._pr.create_issue(
            title, body_out, list(_ISSUE_LABELS_FIND),
        )

    async def _file_escalation(
        self, *, slug: str, cite: Cite, attempts: int,
    ) -> None:
        title = f"Wiki rot stuck: {slug} cites missing {cite.raw}"
        body = (
            "**Escalation — WikiRotDetectorLoop (spec §4.9 / §3.2).**\n\n"
            f"- Repo: `{slug}`\n"
            f"- Broken cite: `{cite.raw}`\n"
            f"- Attempts: `{attempts}` ≥ `{_MAX_ATTEMPTS}` — repair loop "
            "has not closed the finding within the retry budget.\n\n"
            "Human: resolve the cite or remove the wiki entry, then "
            "close this issue. The dedup key + attempt counter clear "
            "automatically on close (spec §3.2).\n"
        )
        await self._pr.create_issue(
            title, body, list(_ISSUE_LABELS_ESCALATE),
        )

    # -- module helpers ----------------------------------------------------


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def _excerpt_around(body: str, needle: str, limit: int) -> str:
    """Return a ≤*limit*-char window centered on *needle* — or the head
    of *body* if *needle* is near the top / absent.
    """
    if len(body) <= limit:
        return body
    idx = body.find(needle)
    if idx < 0:
        return body[:limit]
    start = max(0, idx - limit // 2)
    end = min(len(body), start + limit)
    return body[start:end]
```

- [ ] **Step 4: Re-run — expect all 6 PASS.**

- [ ] **Step 5: Commit:**

  ```bash
  git add src/wiki_rot_detector_loop.py tests/test_wiki_rot_detector_loop.py
  git commit -m "feat(loop): WikiRotDetector per-repo tick + filing + escalation (§4.9)"
  ```

---

## Task 6 — Close-reconcile (dedup/attempt clearance on escalation close)

Per spec §3.2: on closed `hitl-escalation` + `wiki-rot-stuck` authored by the bot, the matching dedup key and attempt counter clear. Polled on every tick — no separate cron.

- [ ] **Step 1: Append failing tests** to `tests/test_wiki_rot_detector_loop.py`:

```python
async def test_reconcile_clears_dedup_and_attempts(
    tmp_path: Path, loop_env, monkeypatch,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    dedup.get.return_value = {
        f"wiki_rot_detector:{slug}:src/foo.py:bar",
        f"wiki_rot_detector:{slug}:src/foo.py:other",  # unrelated, stays
    }
    closed_payload = [
        {
            "number": 901,
            "title": f"Wiki rot stuck: {slug} cites missing src/foo.py:bar",
            "body": f"Repo: `{slug}`",
        },
    ]

    async def fake_list(*_a, **_kw):
        return closed_payload

    loop = _loop(loop_env)
    monkeypatch.setattr(loop, "_gh_closed_escalations", fake_list)

    await loop._reconcile_closed_escalations()

    state.clear_wiki_rot_attempts.assert_any_call(f"{slug}:src/foo.py:bar")
    # set_all called with the surviving key.
    remaining_calls = [c.args[0] for c in dedup.set_all.call_args_list]
    assert remaining_calls, "dedup.set_all not invoked"
    assert f"wiki_rot_detector:{slug}:src/foo.py:bar" not in remaining_calls[-1]
    assert f"wiki_rot_detector:{slug}:src/foo.py:other" in remaining_calls[-1]
```

- [ ] **Step 2: Run — expect FAIL** (stub).

- [ ] **Step 3: Replace the `_reconcile_closed_escalations` stub** with:

```python
    async def _reconcile_closed_escalations(self) -> None:
        """Poll closed ``wiki-rot-stuck`` escalations and clear the
        matching dedup key + attempt counter.  Called at the top of
        every tick; close-to-clear latency is bounded by the loop
        interval (spec §3.2).
        """
        try:
            closed = await self._gh_closed_escalations()
        except Exception:  # noqa: BLE001
            logger.debug("reconcile: gh list failed", exc_info=True)
            return

        if not closed:
            return

        current = self._dedup.get()
        to_clear: set[str] = set()
        for issue in closed:
            subject = _parse_escalation_subject(
                str(issue.get("title", "")), str(issue.get("body", "")),
            )
            if subject is None:
                continue
            key = f"wiki_rot_detector:{subject}"
            if key in current:
                to_clear.add(key)
            self._state.clear_wiki_rot_attempts(subject)

        if to_clear:
            remaining = current - to_clear
            self._dedup.set_all(remaining)

    async def _gh_closed_escalations(self) -> list[dict[str, Any]]:
        """Return the list of closed ``hitl-escalation`` +
        ``wiki-rot-stuck`` issues authored by this bot.

        Shells out to ``gh issue list`` to avoid a PRManager dependency
        on a rarely-used endpoint.  JSON parse / non-zero exit → empty
        list (tolerant — reconciliation is best-effort).
        """
        cmd = [
            "gh", "issue", "list",
            "--state", "closed",
            "--label", "hitl-escalation",
            "--label", "wiki-rot-stuck",
            "--author", "@me",
            "--json", "number,title,body",
            "--limit", "50",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
        except (OSError, FileNotFoundError):
            return []
        if proc.returncode != 0:
            return []
        try:
            data = json.loads(stdout or b"[]")
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []


def _parse_escalation_subject(title: str, body: str) -> str | None:
    """Extract ``{slug}:{cite}`` from an escalation issue.

    Title format: ``Wiki rot stuck: {slug} cites missing {cite}``.
    ``{slug}`` is parsed directly from the title (everything between
    ``stuck: `` and `` cites missing ``); falls back to a ``Repo: `` line
    in the body on malformed titles.
    """
    prefix = "Wiki rot stuck: "
    anchor = " cites missing "
    if not title.startswith(prefix) or anchor not in title:
        return None
    slug_plus_tail = title[len(prefix):]
    slug, _, cite = slug_plus_tail.partition(anchor)
    slug = slug.strip()
    cite = cite.strip()
    if not slug or not cite:
        # Fallback: ``Repo: `slug`` in body.
        for line in body.splitlines():
            if line.strip().startswith("- Repo:") or line.strip().startswith("Repo:"):
                slug = line.split("`")[1] if "`" in line else slug
                break
    if not slug or not cite:
        return None
    return f"{slug}:{cite}"
```

- [ ] **Step 4: Re-run — expect PASS.**

- [ ] **Step 5: Commit:**

  ```bash
  git add src/wiki_rot_detector_loop.py tests/test_wiki_rot_detector_loop.py
  git commit -m "feat(loop): WikiRotDetector close-reconcile clears dedup + attempts (§4.9 / §3.2)"
  ```

---

## Task 7 — Lazy trace emission + kill-switch coverage

- [ ] **Step 1: Append failing tests** to `tests/test_wiki_rot_detector_loop.py`:

```python
async def test_kill_switch_short_circuits_tick(loop_env) -> None:
    loop = _loop(loop_env, enabled=False)
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}


async def test_trace_emission_lazy_import_tolerates_missing_module(
    loop_env, monkeypatch,
) -> None:
    """Importing ``trace_collector`` must not be required — the loop
    runs clean even when the module is absent (spec sibling lock).
    """
    import sys
    # Force ImportError on the emit path.
    monkeypatch.setitem(sys.modules, "trace_collector", None)
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "noop"
```

- [ ] **Step 2: Run — expect the first PASS (kill-switch already wired in Task 4). Expect the second PASS too if you already guarded emission; if not, move on.**

- [ ] **Step 3: If telemetry emission is wanted later**, add at the **end** of `_do_work`, just before the final `return`:

```python
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            emit_loop_subprocess_trace = None  # type: ignore[assignment]
        if emit_loop_subprocess_trace is not None:
            try:
                emit_loop_subprocess_trace(
                    worker=self._worker_name,
                    details={"repos_scanned": scanned, "filed": filed},
                )
            except Exception:  # noqa: BLE001
                logger.debug("trace emission failed", exc_info=True)
```

(Keep this optional — the sibling-plan lock is "tolerate absence," not "require emission.")

- [ ] **Step 4: Re-run — expect PASS.**

- [ ] **Step 5: Commit (only if you added the trace block):**

  ```bash
  git add src/wiki_rot_detector_loop.py tests/test_wiki_rot_detector_loop.py
  git commit -m "feat(loop): WikiRotDetector kill-switch + lazy trace emission (§4.9 / §12.2)"
  ```

---

## Task 8 — Five-checkpoint wiring

One task, five sub-steps. The worker string `wiki_rot_detector` must be verbatim across all five sites — `test_loop_wiring_completeness.py` matches exactly.

- [ ] **Step 1: `src/service_registry.py`**

  - `:63` area — add near the other loop imports:

    ```python
    from wiki_rot_detector_loop import WikiRotDetectorLoop  # noqa: TCH001
    ```

  - `:168` — append a dataclass field after `retrospective_loop`:

    ```python
        wiki_rot_detector_loop: WikiRotDetectorLoop
    ```

  - `:813` — after the `retrospective_loop = RetrospectiveLoop(...)` block, insert:

    ```python
    wiki_rot_dedup = DedupStore(
        "wiki_rot_detector",
        config.data_root / "dedup" / "wiki_rot_detector.json",
    )
    wiki_rot_detector_loop = WikiRotDetectorLoop(  # noqa: F841
        config=config,
        state=state,
        pr_manager=prs,
        dedup=wiki_rot_dedup,
        wiki_store=repo_wiki_store,
        deps=loop_deps,
    )
    ```

  - `:871` — append inside the `return ServiceRegistry(...)` call:

    ```python
        wiki_rot_detector_loop=wiki_rot_detector_loop,
    ```

- [ ] **Step 2: `src/orchestrator.py`**

  - `:158` — append to `bg_loop_registry`:

    ```python
        "wiki_rot_detector": svc.wiki_rot_detector_loop,
    ```

  - `:909` — append to `loop_factories`:

    ```python
        ("wiki_rot_detector", self._svc.wiki_rot_detector_loop.run),
    ```

- [ ] **Step 3: `src/ui/src/constants.js`**

  - `:252` — append `'wiki_rot_detector'` to the `EDITABLE_INTERVAL_WORKERS` Set.
  - `:273` — append to `SYSTEM_WORKER_INTERVALS`:

    ```js
      wiki_rot_detector: 604800,
    ```

  - `:312` — append to `BACKGROUND_WORKERS`:

    ```js
      { key: 'wiki_rot_detector', label: 'Wiki Rot Detector', description: 'Weekly scan of per-repo wikis for broken code cites (file:symbol, dotted src.paths); files hydraflow-find issues with fuzzy-match suggestions.', color: theme.purple, group: 'learning', tags: ['knowledge'] },
    ```

- [ ] **Step 4: `src/dashboard_routes/_common.py`**

  - `:55` — append to `_INTERVAL_BOUNDS`:

    ```python
        "wiki_rot_detector": (86400, 2_592_000),
    ```

- [ ] **Step 5: Verify + commit:**

  ```bash
  PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
  git add src/service_registry.py src/orchestrator.py src/ui/src/constants.js src/dashboard_routes/_common.py
  git commit -m "feat(wiring): WikiRotDetectorLoop five-checkpoint registration (§4.9)"
  ```

  Expected: all five wiring classes green.

---

## Task 9 — Loop-wiring-completeness confirmation + catalog update

Regex discovery in `tests/test_loop_wiring_completeness.py` auto-matches `worker_name="wiki_rot_detector"` — no edit required there.

The scenario catalog, however, must learn the new loop.

**Modify** `tests/scenarios/catalog/loop_registrations.py` — insert above `_BUILDERS`:

```python
def _build_wiki_rot_detector(
    ports: dict[str, Any], config: Any, deps: Any,
) -> Any:
    from wiki_rot_detector_loop import WikiRotDetectorLoop  # noqa: PLC0415

    state = ports.get("wiki_rot_state") or MagicMock()
    dedup = ports.get("wiki_rot_dedup") or MagicMock()
    wiki_store = ports.get("wiki_store") or MagicMock()
    ports.setdefault("wiki_rot_state", state)
    ports.setdefault("wiki_rot_dedup", dedup)
    ports.setdefault("wiki_store", wiki_store)
    return WikiRotDetectorLoop(
        config=config,
        state=state,
        pr_manager=ports["github"],
        dedup=dedup,
        wiki_store=wiki_store,
        deps=deps,
    )
```

Then at `:234` (inside `_BUILDERS`) append:

```python
    "wiki_rot_detector": _build_wiki_rot_detector,
```

**Modify** `tests/scenarios/catalog/test_loop_instantiation.py:34` — append `"wiki_rot_detector",` to `ALL_LOOPS`.

**Modify** `tests/scenarios/catalog/test_loop_registrations.py:34` — append `"wiki_rot_detector",` to `ALL_LOOPS` (and update the docstring count if present).

- [ ] **Step 1: Confirm:**

  ```bash
  PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py tests/scenarios/catalog/ -v
  ```

  Expected: PASS across both files.

- [ ] **Step 2: Commit:**

  ```bash
  git add tests/scenarios/catalog/loop_registrations.py tests/scenarios/catalog/test_loop_instantiation.py tests/scenarios/catalog/test_loop_registrations.py
  git commit -m "test(catalog): register WikiRotDetectorLoop in scenario catalog (§4.9)"
  ```

---

## Task 10 — MockWorld scenario + final verification + PR

**Create** `tests/scenarios/test_wiki_rot_detector_scenario.py`:

```python
"""Scenario: WikiRotDetectorLoop fires on a seeded wiki with a broken cite.

Fabricates a one-entry wiki whose cite points at a real module but a
symbol that does not exist, stubs ``gh issue list`` to return empty
(no prior escalations to reconcile), and asserts one ``hydraflow-find``
+ ``wiki-rot`` issue is filed via the bot's ``create_issue`` port.
"""

from __future__ import annotations

import asyncio as _asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class _FakeProc:
    def __init__(self, stdout: bytes, exit_code: int = 0) -> None:
        self._stdout = stdout
        self.returncode = exit_code

    async def communicate(self):
        return self._stdout, b""


def _seed_wiki(tmp_path: Path, slug: str) -> Path:
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    entry = wiki_dir / "patterns.md"
    entry.write_text(
        "# Patterns\n\n## RepoWikiStore guard\n\n"
        "The guard lives in `src/foo.py:bar` — see ADR-0099.\n"
    )
    return wiki_dir


def _seed_source(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "foo.py").write_text(
        "def other():\n    return 1\n\nclass Unrelated:\n    pass\n"
    )


class TestWikiRotDetectorScenario:
    async def test_fires_on_broken_cite(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        world = MockWorld(tmp_path)
        slug = "hydra/hydraflow"

        wiki_dir = _seed_wiki(tmp_path, slug)
        _seed_source(tmp_path)

        fake_state = MagicMock()
        fake_state.get_wiki_rot_attempts.return_value = 0
        fake_state.inc_wiki_rot_attempts.return_value = 1

        fake_dedup = MagicMock()
        fake_dedup.get.return_value = set()

        fake_wiki_store = MagicMock()
        fake_wiki_store.list_repos.return_value = [slug]
        fake_wiki_store.repo_dir.return_value = wiki_dir

        fake_github = AsyncMock()
        fake_github.create_issue = AsyncMock(return_value=42)

        _seed_ports(
            world,
            github=fake_github,
            wiki_rot_state=fake_state,
            wiki_rot_dedup=fake_dedup,
            wiki_store=fake_wiki_store,
        )

        async def fake_subproc(*argv, **_kwargs):
            if "issue" in argv and "list" in argv:
                return _FakeProc(b"[]")
            return _FakeProc(b"[]")

        monkeypatch.setattr(_asyncio, "create_subprocess_exec", fake_subproc)

        # HydraFlow-self AST verification needs ``config.repo_root`` to
        # point at the seeded tree so ``src/foo.py`` resolves.
        world.config.repo_root = tmp_path  # type: ignore[misc]
        world.config.repo = slug  # type: ignore[misc]

        stats = await world.run_with_loops(["wiki_rot_detector"], cycles=1)

        assert stats["wiki_rot_detector"]["issues_filed"] >= 1, stats
        fake_github.create_issue.assert_awaited()
        labels = fake_github.create_issue.await_args.args[2]
        assert "hydraflow-find" in labels
        assert "wiki-rot" in labels
        title = fake_github.create_issue.await_args.args[0]
        assert "src/foo.py:bar" in title
        body = fake_github.create_issue.await_args.args[1]
        assert "Did you mean" in body  # fuzzy suggestion surfaces
```

- [ ] **Step 1: Run scenario + catalog:**

  ```bash
  PYTHONPATH=src uv run pytest tests/scenarios/test_wiki_rot_detector_scenario.py tests/scenarios/catalog/ -v
  ```

  Expected: PASS.

- [ ] **Step 2: Full quality gate:**

  ```bash
  make quality
  ```

  Hard gate per `docs/agents/quality-gates.md`. Fix anything red.

- [ ] **Step 3: Commit scenario:**

  ```bash
  git add tests/scenarios/test_wiki_rot_detector_scenario.py
  git commit -m "test(scenarios): WikiRotDetector fires on seeded broken cite (§4.9)"
  ```

- [ ] **Step 4: Push + PR:**

  ```bash
  git push -u origin trust-arch-hardening
  gh pr create --title "feat(loop): WikiRotDetectorLoop — weekly wiki cite rot detector (§4.9)" --body "$(cat <<'EOF'
## Summary

- New `WikiRotDetectorLoop` (`src/wiki_rot_detector_loop.py`) — weekly `BaseBackgroundLoop` walking every `RepoWikiStore` repo and verifying cited code references against HydraFlow-self's HEAD (AST) + managed-repo wiki mirrors (grep).
- New helper `src/wiki_rot_citations.py` — three extraction patterns (`path.py:symbol`, dotted `src.module.Class`, fenced-code hints), AST verifier with depth-1 re-export resolution, `difflib` fuzzy suggester.
- Files `hydraflow-find` + `wiki-rot` issues per broken cite via `PRManager.create_issue`; 3-attempt escalation → `hitl-escalation` + `wiki-rot-stuck`, with dedup-clear on close (spec §3.2).
- Kill-switch via `LoopDeps.enabled_cb("wiki_rot_detector")` — **no `wiki_rot_detector_enabled` config field** (spec §12.2).
- State mixin `WikiRotDetectorStateMixin` + one `StateData` field.
- Config field + env override (`HYDRAFLOW_WIKI_ROT_DETECTOR_INTERVAL`, default 7d, bounds 1d–30d).
- Five-checkpoint wiring; scenario catalog updated.
- MockWorld scenario exercises the broken-cite → filed-issue path end-to-end.

## Spec

`docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §4.9 / §3.2 / §12.2.

## Test plan

- [ ] \`PYTHONPATH=src uv run pytest tests/test_state_wiki_rot_detector.py -v\`
- [ ] \`PYTHONPATH=src uv run pytest tests/test_config_wiki_rot_detector.py -v\`
- [ ] \`PYTHONPATH=src uv run pytest tests/test_wiki_rot_citations.py -v\`
- [ ] \`PYTHONPATH=src uv run pytest tests/test_wiki_rot_detector_loop.py -v\`
- [ ] \`PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v\`
- [ ] \`PYTHONPATH=src uv run pytest tests/scenarios/test_wiki_rot_detector_scenario.py tests/scenarios/catalog/ -v\`
- [ ] \`make quality\`

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
  ```

Return the PR URL to the user.

---

## Appendix — quick reference

| Decision | Value | Source |
|---|---|---|
| Worker name | `wiki_rot_detector` | Spec §12.2 |
| Interval | `604800s` (7d), bounds `86400 – 2_592_000` | This plan §16 |
| Style-A regex | `r"\b([\w./-]+\.py):(\w+)"` | Spec §4.9 bullet 2 / This plan §6 |
| Style-B regex | `r"\b(src(?:\.\w+)+)\b"` | This plan §6 |
| Style-C | bare names inside ```` ```python ``` ```` fences; hints only | This plan §6 |
| Verification | AST for self, grep for managed-repo mirrors | Spec §4.9 bullet 3 / This plan §7 |
| Re-export depth | 1 (deeper → grep fallback) | This plan §8 |
| Fuzzy cutoff | `difflib.get_close_matches(n=1, cutoff=0.6)` | This plan §10 |
| Dedup key | `f"wiki_rot_detector:{slug}:{cite}"` | Sibling plan format |
| Escalation threshold | `3` attempts (`>=`) | Spec §4.9 / §3.2 |
| Find labels | `hydraflow-find`, `wiki-rot` | Spec §4.9 |
| Escalation labels | `hitl-escalation`, `wiki-rot-stuck` | Spec §4.9 |
| DedupStore clear | `set_all(remaining)` | Sibling plan |
| Trace emission | `emit_loop_subprocess_trace` lazy-import | Sibling plan |
| Kill-switch | `LoopDeps.enabled_cb("wiki_rot_detector")` only | Spec §12.2 |
| Managed-repo AST | **Out of scope v1** — grep mirror only | This plan §7 |
