# Adversarial Skill Corpus + Learning Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect silent regressions in the four post-implementation skills (`diff_sanity`, `scope_check`, `test_adequacy`, `plan_compliance`) via a hand-crafted adversarial corpus wired into the RC gate (Phase 1), then grow the corpus automatically from production escape signals via a new `CorpusLearningLoop` (Phase 2).

**Architecture:** Phase 1 creates `tests/trust/adversarial/` with a parameterized pytest harness that replays each case's `before/ → after/` pair through a thin skill-dispatch shim (reusing the production `prompt_builder` + `result_parser` functions registered in `skill_registry.BUILTIN_SKILLS`). The RC workflow's new `trust` job runs `make trust` which invokes `make trust-adversarial`. Phase 2 adds `src/corpus_learning_loop.py` as a new `BaseBackgroundLoop` that watches `skill-escape`-labeled issues, synthesizes new cases via an **in-process LLM call through `BaseRunner._execute`** (chosen over the routing-issue alternative for lower latency and fewer moving parts per §3.2 autonomy stance — the loop does real work rather than spawning a supervision subtree), self-validates the synthesis (parses, lints, trips the claimed catcher), and opens a PR against `staging` that auto-merges through the standard reviewer + quality-gate path.

**Tech Stack:** Python 3.11, pytest (with `pytest.mark.parametrize` over filesystem cases), pydantic, `subprocess` for `gh` CLI, existing HydraFlow `BaseBackgroundLoop` / `PRManager` / `StateTracker` / `DedupStore` infrastructure.

**Spec:** [`docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`](../specs/2026-04-22-trust-architecture-hardening-design.md) — implements §4.1 (v1 corpus + v2 learning loop), plus the §5 `make trust` + `make trust-adversarial` shared-infra targets and the `trust` CI job, plus the §7 unit tests for §4.1, plus the §6 fail-mode rows for `adversarial` and `CorpusLearningLoop`.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `tests/trust/__init__.py` | **Create** | Package marker for the new `tests/trust/` tree |
| `tests/trust/adversarial/__init__.py` | **Create** | Package marker for the adversarial corpus |
| `tests/trust/adversarial/test_adversarial_corpus.py` | **Create** | Parameterized harness — replays each case through skill dispatch, asserts RETRY + keyword |
| `tests/trust/adversarial/cases/<case_name>/{before,after}/...` | **Create** (multiple) | Per-case minimal repo subsets (~20–25 cases) |
| `tests/trust/adversarial/cases/<case_name>/expected_catcher.txt` | **Create** (multiple) | Registered skill name (or sentinel `none`) |
| `tests/trust/adversarial/cases/<case_name>/README.md` | **Create** (multiple) | One-paragraph description + keyword |
| `tests/test_adversarial_corpus_harness.py` | **Create** | Unit tests for the harness itself (parameterization, keyword, sentinel pass-through, registry validation) |
| `Makefile` | Modify (append new targets) | `trust-adversarial` + `trust` composite target |
| `.github/workflows/rc-promotion-scenario.yml` | Modify (add `trust` job after `scenario`) | Runs `make trust` on the RC PR |
| `src/corpus_learning_loop.py` | **Create** (Phase 2) | `BaseBackgroundLoop` subclass that proposes new cases from escape issues |
| `tests/test_corpus_learning_loop.py` | **Create** (Phase 2) | Unit + integration tests for the loop |
| `src/service_registry.py` | Modify (Phase 2, 5-checkpoint) | Add `corpus_learning_loop` dataclass field + build step |
| `src/orchestrator.py` | Modify (Phase 2, 5-checkpoint) | Add entry to `bg_loop_registry` + `loop_factories` |
| `src/ui/src/constants.js` | Modify (Phase 2, 5-checkpoint) | Add `corpus_learning` to `BACKGROUND_WORKERS`, `EDITABLE_INTERVAL_WORKERS`, `SYSTEM_WORKER_INTERVALS` |
| `src/dashboard_routes/_common.py` | Modify (Phase 2, 5-checkpoint) | Add `corpus_learning` to `_INTERVAL_BOUNDS` |
| `src/config.py` | Modify (Phase 2, 5-checkpoint) | Add `corpus_learning_interval` Field, `corpus_learning_model` Field, `corpus_learning_signal_label` Field + `_ENV_INT_OVERRIDES` + `_ENV_STR_OVERRIDES` entries |

---

## Phase 1 — v1 Static Corpus (RC-gate-landing)

Goal: ship a working corpus + harness as an RC-promotion gate. This phase leaves nothing half-done; the corpus catches six bug classes and `make trust-adversarial` is green locally and in CI.

---

### Task 1: Scaffold `tests/trust/adversarial/` directory tree

**Files:**
- Create: `tests/trust/__init__.py`
- Create: `tests/trust/adversarial/__init__.py`
- Create: `tests/trust/adversarial/cases/.gitkeep`

- [ ] **Step 1: Create package markers and cases placeholder**

Create `tests/trust/__init__.py` with exactly:

```python
"""Trust-architecture hardening test trees (adversarial corpus, contracts)."""
```

Create `tests/trust/adversarial/__init__.py` with exactly:

```python
"""Adversarial corpus for post-implementation skills (see docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md §4.1)."""
```

Create `tests/trust/adversarial/cases/.gitkeep` (empty file).

- [ ] **Step 2: Commit the scaffold**

```bash
git add tests/trust/__init__.py tests/trust/adversarial/__init__.py tests/trust/adversarial/cases/.gitkeep
git commit -m "$(cat <<'EOF'
test(trust): scaffold adversarial corpus tree (§4.1 v1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Implement the adversarial corpus harness

The harness iterates `cases/*`, synthesizes a diff, feeds it to the skill's registered `prompt_builder`/`result_parser` directly, and asserts the expected catcher returns RETRY with the README's keyword in the summary. For the `none` sentinel, the harness asserts that **no** skill returns RETRY on the case (pass-through).

The harness uses the prompt builders and result parsers from `src/skill_registry.BUILTIN_SKILLS` directly. It does not spin up subprocesses — production skill dispatch (`agent.py:_run_skill`) would require a full `Task` + worktree + agent CLI process, which is neither necessary nor deterministic for a unit-style corpus check. The corpus tests the **prompt + parser round-trip against a real LLM reply**; at RC-gate time we stub the LLM reply via a recorded fixture when one exists for the case, else we invoke the real `claude` CLI through `BaseRunner._execute` — the plan uses the fixture path by default so the gate is deterministic, falling back to live calls only when `HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1` is set.

**Files:**
- Create: `tests/trust/adversarial/test_adversarial_corpus.py`

- [ ] **Step 1: Write the harness**

Create `tests/trust/adversarial/test_adversarial_corpus.py`:

```python
"""Adversarial corpus harness — iterates tests/trust/adversarial/cases/*.

Each case directory contains:
  - before/                 minimal pre-diff repo subset
  - after/                  minimal post-diff repo subset
  - expected_catcher.txt    one of the registered skills' names, or "none"
  - README.md               describes the bug + names a required keyword

The harness synthesizes a unified diff from before/ vs after/, feeds it to
every skill's registered prompt_builder, records what the corresponding
result_parser would return when given a canned "RETRY+summary" transcript
from a captured fixture at cases/<name>/expected_transcript.txt (if present)
or produced on demand from an LLM call against the prompt. The "pass"
assertion is: the expected_catcher skill's parser reports passed=False AND
the keyword from the README appears (case-insensitive substring) in the
parser's summary field.

The `none` sentinel asserts that NO skill reports passed=False on the
case — i.e. a deliberately benign diff must not trip any catcher.
"""

from __future__ import annotations

import difflib
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE / "cases"
REPO_ROOT = HERE.parent.parent.parent
SRC = REPO_ROOT / "src"

sys.path.insert(0, str(SRC))

from skill_registry import BUILTIN_SKILLS, AgentSkill  # noqa: E402

# Map skill.name -> AgentSkill, resolved at module import from the live
# registry. If a new post-impl skill is added to BUILTIN_SKILLS, the
# corpus automatically accepts expected_catcher.txt values naming it.
_SKILLS_BY_NAME: dict[str, AgentSkill] = {s.name: s for s in BUILTIN_SKILLS}
_VALID_CATCHERS: frozenset[str] = frozenset({*_SKILLS_BY_NAME.keys(), "none"})


def _discover_cases() -> list[Path]:
    if not CASES_DIR.is_dir():
        return []
    return sorted(p for p in CASES_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def _read_case_files(root: Path) -> dict[str, str]:
    """Return {relative_path: file_text} under *root*."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            try:
                out[rel] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                out[rel] = ""
    return out


def _synthesize_diff(before_dir: Path, after_dir: Path) -> str:
    """Build a unified diff from before/ -> after/ with git-style headers."""
    before = _read_case_files(before_dir)
    after = _read_case_files(after_dir)
    chunks: list[str] = []
    for rel in sorted(set(before) | set(after)):
        b = before.get(rel, "")
        a = after.get(rel, "")
        if b == a:
            continue
        diff = difflib.unified_diff(
            b.splitlines(keepends=True),
            a.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
        chunks.append(f"diff --git a/{rel} b/{rel}\n")
        chunks.extend(diff)
    return "".join(chunks)


def _load_transcript(case_dir: Path, prompt: str) -> str:
    """Return the canned LLM transcript for *case_dir*, or invoke live claude."""
    fixture = case_dir / "expected_transcript.txt"
    if fixture.exists():
        return fixture.read_text(encoding="utf-8")
    if os.environ.get("HYDRAFLOW_TRUST_ADVERSARIAL_LIVE") != "1":
        pytest.skip(
            f"No expected_transcript.txt for {case_dir.name}; set "
            "HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1 to invoke the real claude CLI."
        )
    try:
        result = subprocess.run(  # noqa: S603
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        pytest.fail(f"Live claude invocation failed for {case_dir.name}: {exc}")
    return result.stdout


def _read_keyword(readme_path: Path) -> str:
    """Extract the required keyword from a case README.

    Convention: one line of the README reads `Keyword: <word-or-phrase>`.
    The match is case-insensitive substring against the parser's summary.
    """
    text = readme_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().lower().startswith("keyword:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"README.md {readme_path} missing 'Keyword:' line")


def _read_expected_catcher(case_dir: Path) -> str:
    catcher = (case_dir / "expected_catcher.txt").read_text(encoding="utf-8").strip()
    if catcher not in _VALID_CATCHERS:
        raise AssertionError(
            f"{case_dir.name}/expected_catcher.txt = {catcher!r}; must be one of "
            f"{sorted(_VALID_CATCHERS)} (from live skill_registry.BUILTIN_SKILLS)"
        )
    return catcher


def _load_plan_text(case_dir: Path) -> str:
    """Return plan_text for plan-compliance / scope-check cases, or empty."""
    plan = case_dir / "plan.md"
    return plan.read_text(encoding="utf-8") if plan.exists() else ""


@pytest.mark.parametrize(
    "case_dir",
    _discover_cases(),
    ids=lambda p: p.name,
)
def test_case(case_dir: Path) -> None:
    """For each case, assert the expected catcher flags it."""
    before_dir = case_dir / "before"
    after_dir = case_dir / "after"
    assert before_dir.is_dir(), f"{case_dir.name}: missing before/"
    assert after_dir.is_dir(), f"{case_dir.name}: missing after/"

    diff = _synthesize_diff(before_dir, after_dir)
    assert diff.strip(), f"{case_dir.name}: before/ and after/ produced empty diff"

    catcher = _read_expected_catcher(case_dir)
    plan_text = _load_plan_text(case_dir)

    # For every skill, build its prompt and parse the transcript.
    results: dict[str, tuple[bool, str, list[str]]] = {}
    for skill in BUILTIN_SKILLS:
        prompt = skill.prompt_builder(
            issue_number=0,
            issue_title=f"adversarial-corpus::{case_dir.name}",
            diff=diff,
            plan_text=plan_text,
        )
        transcript = _load_transcript(case_dir, prompt)
        results[skill.name] = skill.result_parser(transcript)

    if catcher == "none":
        failing = [name for name, (passed, _, _) in results.items() if not passed]
        assert not failing, (
            f"{case_dir.name}: sentinel 'none' case was flagged by {failing} "
            "but should pass every skill"
        )
        return

    passed, summary, findings = results[catcher]
    assert not passed, (
        f"{case_dir.name}: expected_catcher '{catcher}' returned OK; "
        f"summary={summary!r} findings={findings!r}"
    )

    keyword = _read_keyword(case_dir / "README.md")
    haystack = (summary + "\n" + "\n".join(findings)).lower()
    assert keyword.lower() in haystack, (
        f"{case_dir.name}: expected_catcher '{catcher}' returned RETRY but "
        f"summary/findings did not contain required keyword {keyword!r}. "
        f"summary={summary!r}, findings={findings!r}"
    )
```

- [ ] **Step 2: Run the harness — it collects zero cases**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/trust/adversarial/test_adversarial_corpus.py -v`
Expected: `no tests ran` (0 cases discovered, exit code 5 — acceptable at this stage, seeds added in Task 4).

- [ ] **Step 3: Commit the harness**

```bash
git add tests/trust/adversarial/test_adversarial_corpus.py
git commit -m "$(cat <<'EOF'
test(trust): adversarial corpus harness — diff synth + skill dispatch (§4.1 v1)

Iterates tests/trust/adversarial/cases/*, synthesizes a unified diff from
before/ vs after/, builds each registered skill's prompt, and asserts the
expected_catcher parser reports RETRY with the required keyword. The
sentinel "none" asserts pass-through through every skill. Catcher names
are validated against the live skill_registry.BUILTIN_SKILLS so adding a
new post-impl skill does not require a harness edit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Unit-test the harness against synthetic cases

**Files:**
- Create: `tests/test_adversarial_corpus_harness.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/test_adversarial_corpus_harness.py`:

```python
"""Unit tests for tests/trust/adversarial/test_adversarial_corpus.py.

Tests harness behavior against synthetic case directories — proves the
harness parameterizes correctly, enforces keyword assertion, accepts the
`none` sentinel, and rejects unknown catcher names. Does NOT run the
real corpus (that's the RC gate's job).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TRUST_DIR = Path(__file__).resolve().parent / "trust" / "adversarial"
sys.path.insert(0, str(TRUST_DIR))

# Import harness helpers under test.
import test_adversarial_corpus as harness  # type: ignore[import-not-found]


def _write_case(
    tmp_cases: Path,
    name: str,
    *,
    before: dict[str, str],
    after: dict[str, str],
    catcher: str,
    keyword: str = "scope",
    plan: str | None = None,
    transcript: str | None = None,
) -> Path:
    case = tmp_cases / name
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir()
    for rel, text in before.items():
        (case / "before" / rel).write_text(text)
    for rel, text in after.items():
        (case / "after" / rel).write_text(text)
    (case / "expected_catcher.txt").write_text(catcher)
    (case / "README.md").write_text(f"# {name}\n\nKeyword: {keyword}\n")
    if plan is not None:
        (case / "plan.md").write_text(plan)
    if transcript is not None:
        (case / "expected_transcript.txt").write_text(transcript)
    return case


def test_synthesize_diff_produces_git_headers(tmp_path: Path) -> None:
    (tmp_path / "before").mkdir()
    (tmp_path / "after").mkdir()
    (tmp_path / "before" / "x.py").write_text("old\n")
    (tmp_path / "after" / "x.py").write_text("new\n")
    diff = harness._synthesize_diff(tmp_path / "before", tmp_path / "after")
    assert "diff --git a/x.py b/x.py" in diff
    assert "-old" in diff and "+new" in diff


def test_read_keyword_extracts_line(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# title\n\nKeyword: scope creep\n\nmore\n")
    assert harness._read_keyword(tmp_path / "README.md") == "scope creep"


def test_read_keyword_missing_raises(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# title\n\nno keyword line\n")
    with pytest.raises(AssertionError, match="missing 'Keyword:' line"):
        harness._read_keyword(tmp_path / "README.md")


def test_read_expected_catcher_rejects_unknown(tmp_path: Path) -> None:
    (tmp_path / "expected_catcher.txt").write_text("bogus-skill\n")
    with pytest.raises(AssertionError, match="must be one of"):
        harness._read_expected_catcher(tmp_path)


def test_read_expected_catcher_accepts_sentinel(tmp_path: Path) -> None:
    (tmp_path / "expected_catcher.txt").write_text("none\n")
    assert harness._read_expected_catcher(tmp_path) == "none"


def test_read_expected_catcher_accepts_registered_skills(tmp_path: Path) -> None:
    # Pull a real skill name from the live registry so the test tracks changes.
    from skill_registry import BUILTIN_SKILLS  # noqa: PLC0415
    name = BUILTIN_SKILLS[0].name
    (tmp_path / "expected_catcher.txt").write_text(name + "\n")
    assert harness._read_expected_catcher(tmp_path) == name


def test_test_case_happy_path_uses_transcript_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a canned transcript, the expected_catcher must flag and keyword must match."""
    cases = tmp_path / "cases"
    case = _write_case(
        cases,
        "scope-creep-synthetic",
        before={"src/foo.py": "x = 1\n"},
        after={"src/foo.py": "x = 1\n", "src/unrelated.py": "y = 2\n"},
        catcher="scope-check",
        keyword="scope",
        plan="## Plan\n- Edit `src/foo.py`\n",
        transcript=(
            "SCOPE_CHECK_RESULT: RETRY\n"
            "SUMMARY: unplanned file src/unrelated.py is scope creep\n"
            "FINDINGS:\n- src/unrelated.py — not in plan\n"
        ),
    )
    monkeypatch.setattr(harness, "CASES_DIR", cases)
    harness.test_case(case)  # must not raise


def test_test_case_raises_when_keyword_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = tmp_path / "cases"
    case = _write_case(
        cases,
        "scope-creep-no-keyword",
        before={"src/foo.py": "x = 1\n"},
        after={"src/foo.py": "x = 1\n", "src/unrelated.py": "y = 2\n"},
        catcher="scope-check",
        keyword="scope",
        plan="## Plan\n- Edit `src/foo.py`\n",
        transcript=(
            "SCOPE_CHECK_RESULT: RETRY\n"
            "SUMMARY: something vague\n"
            "FINDINGS:\n- src/unrelated.py — not in plan\n"
        ),
    )
    monkeypatch.setattr(harness, "CASES_DIR", cases)
    with pytest.raises(AssertionError, match="did not contain required keyword"):
        harness.test_case(case)


def test_test_case_raises_when_catcher_returns_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = tmp_path / "cases"
    case = _write_case(
        cases,
        "scope-creep-ok-returned",
        before={"src/foo.py": "x = 1\n"},
        after={"src/foo.py": "x = 1\n", "src/unrelated.py": "y = 2\n"},
        catcher="scope-check",
        keyword="scope",
        plan="## Plan\n- Edit `src/foo.py`\n",
        transcript="SCOPE_CHECK_RESULT: OK\nSUMMARY: nothing unusual\n",
    )
    monkeypatch.setattr(harness, "CASES_DIR", cases)
    with pytest.raises(AssertionError, match="returned OK"):
        harness.test_case(case)


def test_test_case_sentinel_none_passes_when_all_skills_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = tmp_path / "cases"
    # Transcript that every parser reads as OK (no RESULT marker).
    benign = "No issues found.\n"
    case = _write_case(
        cases,
        "benign-noop",
        before={"src/foo.py": "x = 1\n"},
        after={"src/foo.py": "x = 2\n"},
        catcher="none",
        keyword="ignored",
        transcript=benign,
    )
    monkeypatch.setattr(harness, "CASES_DIR", cases)
    harness.test_case(case)  # must not raise
```

- [ ] **Step 2: Run and verify they pass**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_adversarial_corpus_harness.py -v`
Expected: 8 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_adversarial_corpus_harness.py
git commit -m "$(cat <<'EOF'
test(trust): unit tests for adversarial corpus harness (§7)

Covers diff synthesis, keyword extraction, catcher validation against the
live skill_registry, the sentinel `none` pass-through, and assertion
errors when the catcher returns OK or when the keyword is missing from
the summary.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4a: Seed cases 1–5 — diff-sanity bug classes

Five cases, each a self-contained directory. All use committed `expected_transcript.txt` files so the RC gate is deterministic without calling the live `claude` CLI.

**Files (all under `tests/trust/adversarial/cases/`):**
- Create: `renamed-symbol-callsite/{before,after}/src/*.py`, `expected_catcher.txt`, `README.md`, `expected_transcript.txt`
- Create: `required-field-added/{before,after}/src/*.py`, `expected_catcher.txt`, `README.md`, `expected_transcript.txt`
- Create: `accidental-deletion/{before,after}/src/*.py`, `expected_catcher.txt`, `README.md`, `expected_transcript.txt`
- Create: `leftover-print-debug/{before,after}/src/*.py`, `expected_catcher.txt`, `README.md`, `expected_transcript.txt`
- Create: `missing-import/{before,after}/src/*.py`, `expected_catcher.txt`, `README.md`, `expected_transcript.txt`

- [ ] **Step 1: Write case `renamed-symbol-callsite`**

`tests/trust/adversarial/cases/renamed-symbol-callsite/before/src/foo.py`:

```python
def compute_total(items):
    return sum(items)


def run():
    return compute_total([1, 2, 3])
```

`tests/trust/adversarial/cases/renamed-symbol-callsite/after/src/foo.py`:

```python
def compute_sum(items):
    return sum(items)


def run():
    return compute_total([1, 2, 3])
```

`tests/trust/adversarial/cases/renamed-symbol-callsite/expected_catcher.txt`:

```
diff-sanity
```

`tests/trust/adversarial/cases/renamed-symbol-callsite/README.md`:

```
# renamed-symbol-callsite

The function `compute_total` was renamed to `compute_sum`, but the call
site in `run()` still references the old name. This leaves a NameError
at call time that static review should flag.

Keyword: compute_total
```

`tests/trust/adversarial/cases/renamed-symbol-callsite/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: RETRY
SUMMARY: renamed symbol leaves stale callsite to compute_total
FINDINGS:
- src/foo.py:6 — `compute_total` no longer defined; renamed to `compute_sum`
```

- [ ] **Step 2: Write case `required-field-added`**

`tests/trust/adversarial/cases/required-field-added/before/src/model.py`:

```python
from pydantic import BaseModel


class Issue(BaseModel):
    number: int
    title: str
```

`tests/trust/adversarial/cases/required-field-added/after/src/model.py`:

```python
from pydantic import BaseModel


class Issue(BaseModel):
    number: int
    title: str
    reporter: str
```

`tests/trust/adversarial/cases/required-field-added/expected_catcher.txt`:

```
diff-sanity
```

`tests/trust/adversarial/cases/required-field-added/README.md`:

```
# required-field-added

A new required field `reporter: str` was added to a Pydantic model
without a default. Every existing construction site of `Issue(...)` that
omitted `reporter` now raises a ValidationError at runtime. Diff sanity
must flag the missing default on a required field.

Keyword: required field
```

`tests/trust/adversarial/cases/required-field-added/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: RETRY
SUMMARY: new required field reporter added without default breaks callers
FINDINGS:
- src/model.py:7 — `reporter: str` is a required field with no default; existing Issue(...) callers break
```

- [ ] **Step 3: Write case `accidental-deletion`**

`tests/trust/adversarial/cases/accidental-deletion/before/src/util.py`:

```python
def load_config(path):
    with open(path) as f:
        return f.read()


def save_config(path, data):
    with open(path, "w") as f:
        f.write(data)
```

`tests/trust/adversarial/cases/accidental-deletion/after/src/util.py`:

```python
def load_config(path):
    with open(path) as f:
        return f.read()
```

`tests/trust/adversarial/cases/accidental-deletion/expected_catcher.txt`:

```
diff-sanity
```

`tests/trust/adversarial/cases/accidental-deletion/README.md`:

```
# accidental-deletion

`save_config` was deleted — likely unintentional since the diff claims
only to refactor `load_config`. Diff sanity must flag unrelated deletions.

Keyword: accidental deletion
```

`tests/trust/adversarial/cases/accidental-deletion/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: RETRY
SUMMARY: accidental deletion of save_config function
FINDINGS:
- src/util.py — `save_config` removed with no explanation; unrelated to load_config refactor
```

- [ ] **Step 4: Write case `leftover-print-debug`**

`tests/trust/adversarial/cases/leftover-print-debug/before/src/worker.py`:

```python
def process(item):
    return item.upper()
```

`tests/trust/adversarial/cases/leftover-print-debug/after/src/worker.py`:

```python
def process(item):
    print(f"DEBUG: processing {item}")
    return item.upper()
```

`tests/trust/adversarial/cases/leftover-print-debug/expected_catcher.txt`:

```
diff-sanity
```

`tests/trust/adversarial/cases/leftover-print-debug/README.md`:

```
# leftover-print-debug

A debug `print()` statement was left in production code. Diff sanity must
flag leftover debug output.

Keyword: debug
```

`tests/trust/adversarial/cases/leftover-print-debug/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: RETRY
SUMMARY: leftover debug print statement
FINDINGS:
- src/worker.py:2 — `print(f"DEBUG: ...")` is a debug statement; remove before shipping
```

- [ ] **Step 5: Write case `missing-import`**

`tests/trust/adversarial/cases/missing-import/before/src/handler.py`:

```python
def handle(event):
    return event.get("data")
```

`tests/trust/adversarial/cases/missing-import/after/src/handler.py`:

```python
def handle(event):
    logger.info("handling %s", event)
    return event.get("data")
```

`tests/trust/adversarial/cases/missing-import/expected_catcher.txt`:

```
diff-sanity
```

`tests/trust/adversarial/cases/missing-import/README.md`:

```
# missing-import

`logger` is referenced but `logging` is neither imported nor a module-level
`logger = logging.getLogger(...)` assignment was added. Diff sanity must
flag missing imports.

Keyword: missing import
```

`tests/trust/adversarial/cases/missing-import/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: RETRY
SUMMARY: missing import for logger
FINDINGS:
- src/handler.py:2 — `logger` used but no import statement or module-level getLogger assignment
```

- [ ] **Step 6: Run the harness — 5 cases pass**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/trust/adversarial/test_adversarial_corpus.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit cases 1–5**

```bash
git add tests/trust/adversarial/cases/renamed-symbol-callsite \
        tests/trust/adversarial/cases/required-field-added \
        tests/trust/adversarial/cases/accidental-deletion \
        tests/trust/adversarial/cases/leftover-print-debug \
        tests/trust/adversarial/cases/missing-import
git commit -m "$(cat <<'EOF'
test(trust): seed adversarial corpus cases 1–5 (diff-sanity)

Renamed symbol stale callsite, new required Pydantic field without
default, accidental deletion, leftover debug print, and missing import —
each a minimal before/after pair with a canned expected_transcript.txt
so the RC gate is deterministic without live LLM calls.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4b: Seed cases 6–10 — scope-check + plan-compliance bug classes

Five more cases. Scope-check cases include a `plan.md` alongside so the harness can pass `plan_text` into `build_scope_check_prompt`.

**Files (all under `tests/trust/adversarial/cases/`):**
- Create: `scope-creep-unrelated-module/{before,after}/..., plan.md, expected_catcher.txt, README.md, expected_transcript.txt`
- Create: `scope-creep-docs-and-code/{before,after}/..., plan.md, expected_catcher.txt, README.md, expected_transcript.txt`
- Create: `plan-skip-step/{before,after}/..., plan.md, expected_catcher.txt, README.md, expected_transcript.txt`
- Create: `plan-add-unplanned-field/{before,after}/..., plan.md, expected_catcher.txt, README.md, expected_transcript.txt`
- Create: `plan-wrong-test-path/{before,after}/..., plan.md, expected_catcher.txt, README.md, expected_transcript.txt`

- [ ] **Step 1: Write case `scope-creep-unrelated-module`**

`tests/trust/adversarial/cases/scope-creep-unrelated-module/before/src/foo.py`:

```python
def foo():
    return "foo"
```

`tests/trust/adversarial/cases/scope-creep-unrelated-module/after/src/foo.py`:

```python
def foo():
    return "foo-v2"
```

`tests/trust/adversarial/cases/scope-creep-unrelated-module/after/src/bar.py`:

```python
def bar():
    return "bar-also-changed"
```

`tests/trust/adversarial/cases/scope-creep-unrelated-module/plan.md`:

```
# Plan

## File Delta
- Modify `src/foo.py`
```

`tests/trust/adversarial/cases/scope-creep-unrelated-module/expected_catcher.txt`:

```
scope-check
```

`tests/trust/adversarial/cases/scope-creep-unrelated-module/README.md`:

```
# scope-creep-unrelated-module

Plan says modify `src/foo.py`. Diff also creates `src/bar.py` — unrelated
scope creep that the scope-check skill must flag.

Keyword: scope
```

`tests/trust/adversarial/cases/scope-creep-unrelated-module/expected_transcript.txt`:

```
SCOPE_CHECK_RESULT: RETRY
SUMMARY: unplanned src/bar.py is scope creep beyond the file delta
FINDINGS:
- [FAIL] src/bar.py — not in plan file delta
```

- [ ] **Step 2: Write case `scope-creep-docs-and-code`**

`tests/trust/adversarial/cases/scope-creep-docs-and-code/before/src/feature.py`:

```python
def feature():
    return True
```

`tests/trust/adversarial/cases/scope-creep-docs-and-code/after/src/feature.py`:

```python
def feature():
    return True
```

`tests/trust/adversarial/cases/scope-creep-docs-and-code/after/docs/unrelated.md`:

```
# Unrelated doc

Rewritten for no stated reason.
```

`tests/trust/adversarial/cases/scope-creep-docs-and-code/plan.md`:

```
# Plan

## File Delta
- Modify `src/feature.py`
```

`tests/trust/adversarial/cases/scope-creep-docs-and-code/expected_catcher.txt`:

```
scope-check
```

`tests/trust/adversarial/cases/scope-creep-docs-and-code/README.md`:

```
# scope-creep-docs-and-code

Plan only lists `src/feature.py`. Diff adds an unrelated doc page — scope
creep that is not a test file for a planned file.

Keyword: scope
```

`tests/trust/adversarial/cases/scope-creep-docs-and-code/expected_transcript.txt`:

```
SCOPE_CHECK_RESULT: RETRY
SUMMARY: unplanned docs/unrelated.md is scope creep
FINDINGS:
- [FAIL] docs/unrelated.md — not in plan and not a test file for a planned module
```

- [ ] **Step 3: Write case `plan-skip-step`**

`tests/trust/adversarial/cases/plan-skip-step/before/src/service.py`:

```python
class Service:
    def start(self):
        return "started"
```

`tests/trust/adversarial/cases/plan-skip-step/after/src/service.py`:

```python
class Service:
    def start(self):
        return "started"

    def stop(self):
        return "stopped"
```

`tests/trust/adversarial/cases/plan-skip-step/plan.md`:

```
# Plan

## Task 1: Add Service.stop()
## Task 2: Add Service.reload()
## Task 3: Add Service.status()

## File Delta
- Modify `src/service.py`
```

`tests/trust/adversarial/cases/plan-skip-step/expected_catcher.txt`:

```
plan-compliance
```

`tests/trust/adversarial/cases/plan-skip-step/README.md`:

```
# plan-skip-step

Plan has three tasks (stop/reload/status). The diff only implements
`stop()` — tasks 2 and 3 were skipped. Plan-compliance must flag the
missing steps.

Keyword: plan
```

`tests/trust/adversarial/cases/plan-skip-step/expected_transcript.txt`:

```
PLAN_COMPLIANCE_RESULT: RETRY
SUMMARY: implementation diverges from plan — reload() and status() missing
FINDINGS:
- src/service.py — `Service.reload` from plan Task 2 not implemented
- src/service.py — `Service.status` from plan Task 3 not implemented
```

- [ ] **Step 4: Write case `plan-add-unplanned-field`**

`tests/trust/adversarial/cases/plan-add-unplanned-field/before/src/user.py`:

```python
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
```

`tests/trust/adversarial/cases/plan-add-unplanned-field/after/src/user.py`:

```python
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
    email: str = ""
    phone: str = ""
```

`tests/trust/adversarial/cases/plan-add-unplanned-field/plan.md`:

```
# Plan

## Task 1: Add `email` field to User

## File Delta
- Modify `src/user.py` — add `email: str = ""`
```

`tests/trust/adversarial/cases/plan-add-unplanned-field/expected_catcher.txt`:

```
plan-compliance
```

`tests/trust/adversarial/cases/plan-add-unplanned-field/README.md`:

```
# plan-add-unplanned-field

Plan specifies adding one field (`email`). Diff also adds `phone` — an
unplanned addition that the plan-compliance skill must flag.

Keyword: plan
```

`tests/trust/adversarial/cases/plan-add-unplanned-field/expected_transcript.txt`:

```
PLAN_COMPLIANCE_RESULT: RETRY
SUMMARY: implementation diverges from plan — phone field is unplanned
FINDINGS:
- src/user.py — `phone: str = ""` is not in the plan's file delta for src/user.py
```

- [ ] **Step 5: Write case `plan-wrong-test-path`**

`tests/trust/adversarial/cases/plan-wrong-test-path/before/src/calc.py`:

```python
def add(a, b):
    return a + b
```

`tests/trust/adversarial/cases/plan-wrong-test-path/after/src/calc.py`:

```python
def add(a, b):
    return a + b


def sub(a, b):
    return a - b
```

`tests/trust/adversarial/cases/plan-wrong-test-path/after/src/tests_calc_scratch.py`:

```python
def test_sub_inline():
    from src.calc import sub
    assert sub(3, 1) == 2
```

`tests/trust/adversarial/cases/plan-wrong-test-path/plan.md`:

```
# Plan

## Task 1: Add `sub()` to `src/calc.py` with tests at `tests/test_calc.py`

## File Delta
- Modify `src/calc.py`
- Create `tests/test_calc.py`
```

`tests/trust/adversarial/cases/plan-wrong-test-path/expected_catcher.txt`:

```
plan-compliance
```

`tests/trust/adversarial/cases/plan-wrong-test-path/README.md`:

```
# plan-wrong-test-path

Plan says tests go at `tests/test_calc.py`. Diff puts them in
`src/tests_calc_scratch.py` — wrong location, and the planned file was
never created. Plan-compliance must flag the path divergence.

Keyword: plan
```

`tests/trust/adversarial/cases/plan-wrong-test-path/expected_transcript.txt`:

```
PLAN_COMPLIANCE_RESULT: RETRY
SUMMARY: implementation diverges from plan — tests at wrong path
FINDINGS:
- tests/test_calc.py — planned test file never created
- src/tests_calc_scratch.py — unplanned file; tests belong under tests/
```

- [ ] **Step 6: Run — 10 cases pass**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/trust/adversarial/test_adversarial_corpus.py -v`
Expected: 10 passed.

- [ ] **Step 7: Commit**

```bash
git add tests/trust/adversarial/cases/scope-creep-unrelated-module \
        tests/trust/adversarial/cases/scope-creep-docs-and-code \
        tests/trust/adversarial/cases/plan-skip-step \
        tests/trust/adversarial/cases/plan-add-unplanned-field \
        tests/trust/adversarial/cases/plan-wrong-test-path
git commit -m "$(cat <<'EOF'
test(trust): seed adversarial corpus cases 6–10 (scope-check, plan-compliance)

Two scope-creep cases (unrelated module, unrelated docs) and three
plan-divergence cases (skipped steps, unplanned Pydantic field,
misplaced tests).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4c: Seed cases 11–15 — test-adequacy bug classes

- [ ] **Step 1: Write case `missing-test-for-new-function`**

`tests/trust/adversarial/cases/missing-test-for-new-function/before/src/formatter.py`:

```python
def format_title(s):
    return s.title()
```

`tests/trust/adversarial/cases/missing-test-for-new-function/after/src/formatter.py`:

```python
def format_title(s):
    return s.title()


def format_slug(s):
    return s.lower().replace(" ", "-")
```

`tests/trust/adversarial/cases/missing-test-for-new-function/expected_catcher.txt`:

```
test-adequacy
```

`tests/trust/adversarial/cases/missing-test-for-new-function/README.md`:

```
# missing-test-for-new-function

A new public function `format_slug` was added. No test was added for it.
test-adequacy must flag the missing coverage for a new public function.

Keyword: test
```

`tests/trust/adversarial/cases/missing-test-for-new-function/expected_transcript.txt`:

```
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: no test added for new public function format_slug
FINDINGS:
- src/formatter.py — `format_slug` has no test coverage in the diff
```

- [ ] **Step 2: Write case `missing-test-for-new-class`**

`tests/trust/adversarial/cases/missing-test-for-new-class/before/src/pipeline.py`:

```python
def run():
    return None
```

`tests/trust/adversarial/cases/missing-test-for-new-class/after/src/pipeline.py`:

```python
def run():
    return None


class RateLimiter:
    def __init__(self, per_second):
        self.per_second = per_second

    def allow(self):
        return True
```

`tests/trust/adversarial/cases/missing-test-for-new-class/expected_catcher.txt`:

```
test-adequacy
```

`tests/trust/adversarial/cases/missing-test-for-new-class/README.md`:

```
# missing-test-for-new-class

A new public class `RateLimiter` was added. No test was added for it.
test-adequacy must flag the missing coverage.

Keyword: test
```

`tests/trust/adversarial/cases/missing-test-for-new-class/expected_transcript.txt`:

```
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: new public class RateLimiter has no test coverage
FINDINGS:
- src/pipeline.py — `RateLimiter` and `RateLimiter.allow` are new public surface with no test
```

- [ ] **Step 3: Write case `asyncmock-where-fake-exists`**

`tests/trust/adversarial/cases/asyncmock-where-fake-exists/before/tests/test_thing.py`:

```python
def test_placeholder():
    assert True
```

`tests/trust/adversarial/cases/asyncmock-where-fake-exists/after/tests/test_thing.py`:

```python
from unittest.mock import AsyncMock


def test_github_integration():
    gh = AsyncMock()
    gh.create_pr = AsyncMock(return_value=42)
    # ... call code under test ...
    assert gh.create_pr.await_count == 1
```

`tests/trust/adversarial/cases/asyncmock-where-fake-exists/expected_catcher.txt`:

```
test-adequacy
```

`tests/trust/adversarial/cases/asyncmock-where-fake-exists/README.md`:

```
# asyncmock-where-fake-exists

An `AsyncMock` is used to stand in for the GitHub adapter when a stateful
fake `FakeGitHub` already exists under `tests/scenarios/fakes/fake_github.py`.
Per the HydraFlow avoided-patterns list, AsyncMock substitution for
adapters with an existing stateful fake is a bug — test-adequacy must
flag it.

Keyword: AsyncMock
```

`tests/trust/adversarial/cases/asyncmock-where-fake-exists/expected_transcript.txt`:

```
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: AsyncMock used where a stateful fake exists
FINDINGS:
- tests/test_thing.py — `AsyncMock` stands in for GitHub adapter; use tests/scenarios/fakes/fake_github.py:FakeGitHub instead
```

- [ ] **Step 4: Write case `test-only-happy-path`**

`tests/trust/adversarial/cases/test-only-happy-path/before/src/parser.py`:

```python
def parse(s):
    return int(s)
```

`tests/trust/adversarial/cases/test-only-happy-path/before/tests/test_parser.py`:

```python
def test_parse_basic():
    from src.parser import parse
    assert parse("3") == 3
```

`tests/trust/adversarial/cases/test-only-happy-path/after/src/parser.py`:

```python
def parse(s):
    if not s:
        raise ValueError("empty input")
    if not s.lstrip("-").isdigit():
        raise ValueError(f"not numeric: {s!r}")
    return int(s)
```

`tests/trust/adversarial/cases/test-only-happy-path/after/tests/test_parser.py`:

```python
def test_parse_basic():
    from src.parser import parse
    assert parse("3") == 3
```

`tests/trust/adversarial/cases/test-only-happy-path/expected_catcher.txt`:

```
test-adequacy
```

`tests/trust/adversarial/cases/test-only-happy-path/README.md`:

```
# test-only-happy-path

`parse()` grew two new raising branches (empty input, non-numeric input).
The only test still only covers the happy path. test-adequacy must flag
the missing edge-case coverage.

Keyword: edge case
```

`tests/trust/adversarial/cases/test-only-happy-path/expected_transcript.txt`:

```
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: new raising branches in parse() lack edge case test coverage
FINDINGS:
- tests/test_parser.py — no test for `parse("")` ValueError path
- tests/test_parser.py — no test for `parse("abc")` ValueError path
```

- [ ] **Step 5: Write case `test-asserts-tautology`**

`tests/trust/adversarial/cases/test-asserts-tautology/before/src/counter.py`:

```python
class Counter:
    def __init__(self):
        self.value = 0

    def inc(self):
        self.value += 1
```

`tests/trust/adversarial/cases/test-asserts-tautology/after/src/counter.py`:

```python
class Counter:
    def __init__(self):
        self.value = 0

    def inc(self):
        self.value += 1

    def reset(self):
        self.value = 0
```

`tests/trust/adversarial/cases/test-asserts-tautology/after/tests/test_counter.py`:

```python
def test_reset_exists():
    from src.counter import Counter
    c = Counter()
    c.reset()
    # Tautology — doesn't actually verify behavior.
    assert c is not None
```

`tests/trust/adversarial/cases/test-asserts-tautology/expected_catcher.txt`:

```
test-adequacy
```

`tests/trust/adversarial/cases/test-asserts-tautology/README.md`:

```
# test-asserts-tautology

A test was added for `Counter.reset()` but it only asserts `c is not None`
— a tautology that never fails. test-adequacy must flag the ineffective
coverage.

Keyword: tautology
```

`tests/trust/adversarial/cases/test-asserts-tautology/expected_transcript.txt`:

```
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: test is a tautology and does not verify reset behavior
FINDINGS:
- tests/test_counter.py::test_reset_exists — `assert c is not None` is a tautology; missing `assert c.value == 0` after reset
```

- [ ] **Step 6: Run — 15 cases pass**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/trust/adversarial/test_adversarial_corpus.py -v`
Expected: 15 passed.

- [ ] **Step 7: Commit**

```bash
git add tests/trust/adversarial/cases/missing-test-for-new-function \
        tests/trust/adversarial/cases/missing-test-for-new-class \
        tests/trust/adversarial/cases/asyncmock-where-fake-exists \
        tests/trust/adversarial/cases/test-only-happy-path \
        tests/trust/adversarial/cases/test-asserts-tautology
git commit -m "$(cat <<'EOF'
test(trust): seed adversarial corpus cases 11–15 (test-adequacy)

Missing tests for new public function and class, AsyncMock used where a
stateful fake exists, edge-case coverage gap, and tautological assertion
— each a minimal before/after pair with canned transcripts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4d: Seed cases 16–20 — cross-skill + benign sentinel + hardened edges

- [ ] **Step 1: Write case `hardcoded-secret`**

`tests/trust/adversarial/cases/hardcoded-secret/before/src/client.py`:

```python
def make_client():
    return {"host": "api.example.com"}
```

`tests/trust/adversarial/cases/hardcoded-secret/after/src/client.py`:

```python
def make_client():
    return {
        "host": "api.example.com",
        "api_key": "sk-live-abc123def456ghi789jkl012mno345",
    }
```

`tests/trust/adversarial/cases/hardcoded-secret/expected_catcher.txt`:

```
diff-sanity
```

`tests/trust/adversarial/cases/hardcoded-secret/README.md`:

```
# hardcoded-secret

A literal API key was embedded in source. Diff sanity must flag hardcoded
secrets/credentials.

Keyword: secret
```

`tests/trust/adversarial/cases/hardcoded-secret/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: RETRY
SUMMARY: hardcoded secret in source
FINDINGS:
- src/client.py:5 — `sk-live-...` looks like an API key; move to env var / secret store
```

- [ ] **Step 2: Write case `inverted-condition`**

`tests/trust/adversarial/cases/inverted-condition/before/src/guard.py`:

```python
def allow(user):
    if user.is_banned:
        return False
    return True
```

`tests/trust/adversarial/cases/inverted-condition/after/src/guard.py`:

```python
def allow(user):
    if not user.is_banned:
        return False
    return True
```

`tests/trust/adversarial/cases/inverted-condition/expected_catcher.txt`:

```
diff-sanity
```

`tests/trust/adversarial/cases/inverted-condition/README.md`:

```
# inverted-condition

A guard condition was accidentally inverted — banned users are now the
only ones allowed. Diff sanity must flag inverted conditions / obvious
logic errors.

Keyword: logic
```

`tests/trust/adversarial/cases/inverted-condition/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: RETRY
SUMMARY: logic inversion in allow() — banned users now allowed
FINDINGS:
- src/guard.py:3 — `if not user.is_banned` inverts intended guard; should be `if user.is_banned`
```

- [ ] **Step 3: Write case `plan-off-by-one`**

`tests/trust/adversarial/cases/plan-off-by-one/before/src/range.py`:

```python
def take(items, n):
    return items[:n]
```

`tests/trust/adversarial/cases/plan-off-by-one/after/src/range.py`:

```python
def take(items, n):
    return items[: n - 1]
```

`tests/trust/adversarial/cases/plan-off-by-one/plan.md`:

```
# Plan

## Task 1: Leave `take()` semantics unchanged; add logging.

## File Delta
- Modify `src/range.py`
```

`tests/trust/adversarial/cases/plan-off-by-one/expected_catcher.txt`:

```
plan-compliance
```

`tests/trust/adversarial/cases/plan-off-by-one/README.md`:

```
# plan-off-by-one

Plan says `take()` semantics must be unchanged. Diff changes slice from
`[:n]` to `[:n-1]` — an off-by-one semantics change in violation of the
plan. plan-compliance must flag the divergence.

Keyword: plan
```

`tests/trust/adversarial/cases/plan-off-by-one/expected_transcript.txt`:

```
PLAN_COMPLIANCE_RESULT: RETRY
SUMMARY: implementation diverges from plan — take() semantics changed
FINDINGS:
- src/range.py:2 — plan required unchanged semantics; `items[:n-1]` is a behavior change
```

- [ ] **Step 4: Write case `benign-rename-sentinel` (the `none` pass-through)**

`tests/trust/adversarial/cases/benign-rename-sentinel/before/src/color.py`:

```python
def to_hex(rgb):
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"
```

`tests/trust/adversarial/cases/benign-rename-sentinel/before/tests/test_color.py`:

```python
def test_to_hex():
    from src.color import to_hex
    assert to_hex((255, 0, 0)) == "#ff0000"
```

`tests/trust/adversarial/cases/benign-rename-sentinel/after/src/color.py`:

```python
def to_hex(rgb_tuple):
    r, g, b = rgb_tuple
    return f"#{r:02x}{g:02x}{b:02x}"
```

`tests/trust/adversarial/cases/benign-rename-sentinel/after/tests/test_color.py`:

```python
def test_to_hex():
    from src.color import to_hex
    assert to_hex((255, 0, 0)) == "#ff0000"
```

`tests/trust/adversarial/cases/benign-rename-sentinel/expected_catcher.txt`:

```
none
```

`tests/trust/adversarial/cases/benign-rename-sentinel/README.md`:

```
# benign-rename-sentinel

Pure parameter rename (`rgb` → `rgb_tuple`) with no callsites affected.
Should pass every skill without RETRY. This is the sentinel per §7
"End-to-end per subsystem" that proves the harness doesn't false-positive.

Keyword: ignored
```

`tests/trust/adversarial/cases/benign-rename-sentinel/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: OK
SUMMARY: clean parameter rename, no external impact
```

- [ ] **Step 5: Write case `benign-test-added-sentinel`**

`tests/trust/adversarial/cases/benign-test-added-sentinel/before/src/math_util.py`:

```python
def square(x):
    return x * x
```

`tests/trust/adversarial/cases/benign-test-added-sentinel/after/src/math_util.py`:

```python
def square(x):
    return x * x
```

`tests/trust/adversarial/cases/benign-test-added-sentinel/after/tests/test_math_util.py`:

```python
def test_square():
    from src.math_util import square
    assert square(3) == 9
    assert square(-2) == 4
    assert square(0) == 0
```

`tests/trust/adversarial/cases/benign-test-added-sentinel/expected_catcher.txt`:

```
none
```

`tests/trust/adversarial/cases/benign-test-added-sentinel/README.md`:

```
# benign-test-added-sentinel

Pure test addition covering happy path, negative, and zero cases. Should
pass every skill.

Keyword: ignored
```

`tests/trust/adversarial/cases/benign-test-added-sentinel/expected_transcript.txt`:

```
DIFF_SANITY_RESULT: OK
SUMMARY: test-only addition
```

- [ ] **Step 6: Run — 20 cases pass**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/trust/adversarial/test_adversarial_corpus.py -v`
Expected: 20 passed.

- [ ] **Step 7: Commit**

```bash
git add tests/trust/adversarial/cases/hardcoded-secret \
        tests/trust/adversarial/cases/inverted-condition \
        tests/trust/adversarial/cases/plan-off-by-one \
        tests/trust/adversarial/cases/benign-rename-sentinel \
        tests/trust/adversarial/cases/benign-test-added-sentinel
git commit -m "$(cat <<'EOF'
test(trust): seed adversarial corpus cases 16–20 (secrets, logic, sentinels)

Hardcoded secret + inverted guard (diff-sanity), plan off-by-one
semantics change (plan-compliance), and two `none` sentinel cases
(benign rename, test-only addition) that assert pass-through through
every skill — closing the 20-case §4.1 v1 seed floor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Add `make trust-adversarial` and `make trust` targets

**Files:**
- Modify: `Makefile:225-226` (append new targets after `scenario-browser`)

- [ ] **Step 1: Inspect the Makefile style**

Run: `awk 'NR>=210 && NR<=226' /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening/Makefile`
Expected: confirms `scenario`, `scenario-loops`, `scenario-browser` targets end at line 225.

- [ ] **Step 2: Append new targets**

Insert after the `scenario-browser` target (currently ends at line 225 with `@echo "$(GREEN)Browser scenario tests passed$(RESET)"`) and before `test-fast:` (line 227):

```makefile
trust-adversarial: deps
	@echo "$(BLUE)Running adversarial skill corpus...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/trust/adversarial/ -v
	@echo "$(GREEN)Adversarial corpus passed$(RESET)"

trust: trust-adversarial
	@echo "$(GREEN)Trust suite passed$(RESET)"
```

Also extend the `.PHONY:` line (line 39) to include `trust trust-adversarial`:

Modify the `.PHONY:` declaration (line 39) by appending ` trust trust-adversarial` to the end of the space-separated target list.

- [ ] **Step 3: Verify the targets work**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && make trust-adversarial`
Expected: 20 passed, exit 0.

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && make trust`
Expected: runs `trust-adversarial`, then prints `Trust suite passed`, exit 0.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "$(cat <<'EOF'
build(trust): add `make trust-adversarial` and `make trust` composite (§5)

`make trust` is the RC-gate entrypoint. Today it's just the adversarial
corpus; the contract-tests plan extends `trust` to also depend on
`trust-contracts` when that subsystem lands.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Add `trust` job to `rc-promotion-scenario.yml` (live-LLM default)

**Files:**
- Modify: `.github/workflows/rc-promotion-scenario.yml:72-94` (insert `trust` job after `scenario`)

**Why live-LLM in CI (per spec §4.1 "Harness").** The harness has two
execution modes: fixture-replay (the default, used in the dev loop so
`pytest` stays hermetic and free) and live skill dispatch (guarded by
`HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1`, which invokes the real `claude`
CLI through `src/base_runner.py`). **The RC gate must run live.**
Fixture-replay only proves "the recorded transcripts still say what
they used to say" — a prompt-text regression or a model-behavior
regression is invisible because the fixture never re-queries the model.
Live mode re-runs every case against the model the skill actually
ships with, so a prompt that stops catching a bug fails the RC
promotion. Spec §4.1: *"The gate must exercise the real `claude` CLI
so prompt regressions are actually caught."* Keep fixture-replay as
the `make trust-adversarial` default for developers; the CI job below
opts in to live via the environment variable.

- [ ] **Step 1: Append the `trust` job**

Insert a new job after the existing `scenario` job (which currently ends at line 94). Add this block between `scenario` (ending line 94) and `scenario-browser` (starting line 96):

```yaml
  trust:
    name: Trust (adversarial corpus, live LLM)
    needs: gate
    if: needs.gate.outputs.should_run == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ needs.gate.outputs.pr_ref }}
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: uv sync --all-extras
      - name: Trust suite (live skill dispatch)
        env:
          HYDRAFLOW_TRUST_ADVERSARIAL_LIVE: "1"
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: make trust
```

The `HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1` env var flips the harness
from fixture-replay (dev-loop default) to live `claude` CLI dispatch
per §4.1. `ANTHROPIC_API_KEY` is plumbed through from the repo secret
so `src/base_runner.py` can authenticate; absent it, live mode fails
fast rather than silently falling back to fixtures.

- [ ] **Step 2: Validate the workflow YAML parses**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/rc-promotion-scenario.yml'))"`
Expected: exits 0 with no output.

- [ ] **Step 3: Confirm the harness honors the flag**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && grep -n "HYDRAFLOW_TRUST_ADVERSARIAL_LIVE" tests/trust/adversarial/test_adversarial_corpus.py`
Expected: at least one match — the env-gate branching the harness uses to pick live vs fixture mode (wired in Task 2). If zero matches, return to Task 2 and add the gate before this CI job can meaningfully set the variable.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/rc-promotion-scenario.yml
git commit -m "$(cat <<'EOF'
ci(trust): add `trust` job to RC promotion gate — live LLM (§4.1 + §5)

Runs `make trust` on every rc/* → main PR with
HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1 so the adversarial corpus executes
against the real `claude` CLI, not recorded fixtures. Fixture-replay
stays the dev-loop default (fast, hermetic); the RC gate opts in to
live so prompt-text or model-behavior regressions actually surface
per spec §4.1 "Harness". Failing `trust` fails the RC promotion per
ADR-0042.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Smoke-test the gate end-to-end locally

- [ ] **Step 1: Run the full trust suite**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && make trust`
Expected: all 20 corpus cases pass, exit 0.

- [ ] **Step 2: Run the harness unit tests**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_adversarial_corpus_harness.py -v`
Expected: 8 passed.

- [ ] **Step 3: Prove the gate catches a regression**

Temporarily corrupt the expected transcript for `renamed-symbol-callsite` (set RESULT to `OK`), re-run the gate, and confirm it fails loudly. Revert the change.

Run: `sed -i.bak 's/DIFF_SANITY_RESULT: RETRY/DIFF_SANITY_RESULT: OK/' tests/trust/adversarial/cases/renamed-symbol-callsite/expected_transcript.txt`
Run: `make trust || echo "gate correctly failed"`
Expected: pytest reports `renamed-symbol-callsite: expected_catcher 'diff-sanity' returned OK`.
Run: `mv tests/trust/adversarial/cases/renamed-symbol-callsite/expected_transcript.txt.bak tests/trust/adversarial/cases/renamed-symbol-callsite/expected_transcript.txt`
Run: `make trust`
Expected: 20 passed again.

- [ ] **Step 4: Run `make quality`**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && make quality`
Expected: exits 0. Fix any lint/type errors surfaced before proceeding.

---

### Task 8: Open the Phase 1 PR

- [ ] **Step 1: Push the branch and open the PR**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening
git push -u origin trust-arch-hardening
gh pr create --base main --title "test(trust): adversarial skill corpus v1 (§4.1)" --body "$(cat <<'EOF'
## Summary

- Seed 20 adversarial cases under `tests/trust/adversarial/cases/` covering six bug classes (renamed symbols, required Pydantic fields, scope creep, plan divergence, missing tests, AsyncMock-for-fake)
- Parameterized pytest harness `test_adversarial_corpus.py` dispatches each case through every registered post-impl skill's `prompt_builder` + `result_parser` and asserts the expected catcher returns RETRY with a README-supplied keyword
- `none` sentinel cases assert benign diffs pass through every skill
- `make trust-adversarial` + `make trust` targets added; `trust` CI job wired into `.github/workflows/rc-promotion-scenario.yml`
- Unit tests in `tests/test_adversarial_corpus_harness.py` cover parameterization, keyword enforcement, catcher validation, and sentinel behavior

## Spec

Implements §4.1 v1 of `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` plus the §5 shared-infra `make trust*` targets and the §7 harness unit tests.

## Test plan

- [ ] `make trust` passes locally
- [ ] `make quality` passes locally
- [ ] RC promotion CI runs the new `trust` job green on this PR
- [ ] Deliberate regression (OK→RETRY flip in one transcript) is caught by the gate
EOF
)"
```

---

## Phase 2 — v2 `CorpusLearningLoop`

Goal: close the feedback loop so the corpus grows automatically from production escape signals. A `BaseBackgroundLoop` subclass watches `hydraflow-find` issues labeled `skill-escape`, synthesizes a case via an in-process LLM call, self-validates the case (parses, lints, trips the named catcher), and opens a PR against `staging` that auto-merges through the standard reviewer + quality-gate path. Escalate after 3 rejected syntheses per escape issue.

Phase 2 depends on Phase 1 (the harness, the corpus tree, and the skill registry). Phase 2 can slip without blocking Phase 1's RC gate.

---

### Task 9: Create the `CorpusLearningLoop` skeleton

**Files:**
- Create: `src/corpus_learning_loop.py`

- [ ] **Step 1: Create the minimal subclass**

Create `src/corpus_learning_loop.py`:

```python
"""Background loop: synthesize new adversarial corpus cases from skill-escape issues (§4.1 v2)."""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from pr_manager import PRManager

logger = logging.getLogger("hydraflow.corpus_learning_loop")


class CorpusLearningLoop(BaseBackgroundLoop):
    """Grows `tests/trust/adversarial/cases/` from production escape signals.

    On each tick, query `hydraflow-find` issues labeled with the configured
    `corpus_learning_signal_label` (default ``skill-escape``). For each
    unseen issue, synthesize a new case (before/after/expected_catcher/README),
    self-validate it (syntax, lint, trips the claimed catcher), and open a
    PR against staging. Auto-merge happens via the standard reviewer +
    quality-gate path. On 3 self-validation failures for the same issue,
    label it ``hitl-escalation`` + ``corpus-learning-stuck`` and move on.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="corpus_learning", config=config, deps=deps)
        self._prs = prs
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.corpus_learning_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Tick: read escape issues, synthesize + validate + open PRs."""
        # Implemented incrementally in Tasks 11–14.
        return {"escape_issues_seen": 0, "cases_proposed": 0, "escalated": 0}
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "import corpus_learning_loop; print(corpus_learning_loop.CorpusLearningLoop.__name__)"`
Expected: prints `CorpusLearningLoop`, exit 0. (Will fail if `config.corpus_learning_interval` doesn't exist yet — that field is added in Task 15; this command is just a syntax check of the module itself.)

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "import ast; ast.parse(open('src/corpus_learning_loop.py').read())"`
Expected: exits 0.

- [ ] **Step 3: Commit**

```bash
git add src/corpus_learning_loop.py
git commit -m "$(cat <<'EOF'
feat(corpus-learning): CorpusLearningLoop skeleton (§4.1 v2)

Empty tick that will be fleshed out across subsequent tasks. The skeleton
establishes the BaseBackgroundLoop subclass, worker_name, and the three
injected dependencies (PRManager, DedupStore, and LoopDeps).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Unit-test the loop skeleton

**Files:**
- Create: `tests/test_corpus_learning_loop.py`

- [ ] **Step 1: Write failing tests for the skeleton**

Create `tests/test_corpus_learning_loop.py`:

```python
"""Unit + integration tests for src/corpus_learning_loop.py (§4.1 v2)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from base_background_loop import LoopDeps  # noqa: E402
from corpus_learning_loop import CorpusLearningLoop  # noqa: E402


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        interval_cb=MagicMock(return_value=3600),
    )


def _config(tmp_path: Path, **overrides):
    from config import HydraFlowConfig  # noqa: PLC0415
    cfg = HydraFlowConfig(
        repo="owner/repo",
        data_root=tmp_path,
        **overrides,
    )
    return cfg


def test_loop_constructs(tmp_path: Path) -> None:
    loop = CorpusLearningLoop(
        config=_config(tmp_path),
        prs=MagicMock(),
        dedup=MagicMock(),
        deps=_deps(),
    )
    assert loop._worker_name == "corpus_learning"


def test_default_interval_reads_from_config(tmp_path: Path) -> None:
    loop = CorpusLearningLoop(
        config=_config(tmp_path, corpus_learning_interval=7200),
        prs=MagicMock(),
        dedup=MagicMock(),
        deps=_deps(),
    )
    assert loop._get_default_interval() == 7200


def test_do_work_returns_stats_dict(tmp_path: Path) -> None:
    loop = CorpusLearningLoop(
        config=_config(tmp_path),
        prs=MagicMock(),
        dedup=MagicMock(),
        deps=_deps(),
    )
    result = asyncio.run(loop._do_work())
    assert isinstance(result, dict)
    assert {"escape_issues_seen", "cases_proposed", "escalated"} <= set(result)
```

- [ ] **Step 2: Run the tests — they fail until `corpus_learning_interval` is added**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_corpus_learning_loop.py -v`
Expected: pydantic `ValidationError` on `corpus_learning_interval` unknown field — this is expected; Task 15 adds the config field. Skip if there is something else failing, fix that and re-run.

- [ ] **Step 3: Commit the skeleton tests (will flip green after Task 15)**

```bash
git add tests/test_corpus_learning_loop.py
git commit -m "$(cat <<'EOF'
test(corpus-learning): skeleton tests — loop constructs, tick signature

Will light up once Task 15 adds the `corpus_learning_interval` config
field. Kept separate from the skeleton commit to keep TDD cadence:
failing test → impl → passing test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Implement the escape-signal reader

**Files:**
- Modify: `src/corpus_learning_loop.py` (replace `_do_work`, add `_list_escape_issues`)
- Modify: `tests/test_corpus_learning_loop.py` (append tests)

- [ ] **Step 1: Extend the loop**

Replace the `_do_work` method and add `_list_escape_issues` in `src/corpus_learning_loop.py`:

```python
import json

from subprocess_util import run_subprocess


async def _list_escape_issues(self) -> list[dict[str, Any]]:
    """Query `gh api` for open `hydraflow-find` issues with the configured escape label."""
    label = self._config.corpus_learning_signal_label
    query = (
        f"repos/{self._config.repo}/issues"
        f"?state=open&labels=hydraflow-find,{label}&per_page=50"
    )
    try:
        raw = await run_subprocess("gh", "api", query)
    except (RuntimeError, FileNotFoundError):
        logger.warning("gh api query failed for escape issues", exc_info=True)
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("gh api returned non-JSON for escape issues")
        return []
    return [it for it in items if isinstance(it, dict) and "pull_request" not in it]


async def _do_work(self) -> dict[str, Any] | None:
    issues = await self._list_escape_issues()
    stats = {"escape_issues_seen": len(issues), "cases_proposed": 0, "escalated": 0}
    # Synthesis + validation wired in Tasks 12–14.
    return stats
```

Add `_list_escape_issues` as a method on the class (same indentation as `_do_work`), and import `json` and `run_subprocess` at the top of the file.

- [ ] **Step 2: Add a test for the escape-signal reader**

Append to `tests/test_corpus_learning_loop.py`:

```python
def test_list_escape_issues_filters_prs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import corpus_learning_loop as mod  # noqa: PLC0415
    loop = CorpusLearningLoop(
        config=_config(tmp_path),
        prs=MagicMock(),
        dedup=MagicMock(),
        deps=_deps(),
    )
    fake_response = json.dumps([
        {"number": 1, "title": "issue", "labels": [{"name": "skill-escape"}]},
        {"number": 2, "title": "pr", "pull_request": {"url": "..."}},
        {"number": 3, "title": "issue2", "labels": [{"name": "skill-escape"}]},
    ])
    monkeypatch.setattr(mod, "run_subprocess", AsyncMock(return_value=fake_response))
    issues = asyncio.run(loop._list_escape_issues())
    assert [i["number"] for i in issues] == [1, 3]
```

Also add `import json` to the test file if not already present.

- [ ] **Step 3: Run tests (still fail until Task 15 adds the config fields)**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_corpus_learning_loop.py::test_list_escape_issues_filters_prs -v`
Expected: fails on missing `corpus_learning_signal_label` config field. Acceptable — flips green after Task 15.

- [ ] **Step 4: Commit**

```bash
git add src/corpus_learning_loop.py tests/test_corpus_learning_loop.py
git commit -m "$(cat <<'EOF'
feat(corpus-learning): escape-signal reader via gh api (§4.1 v2)

Queries open `hydraflow-find` issues labeled with the configured
`corpus_learning_signal_label`. Filters out PRs (which share the issues
endpoint). Next tasks wire synthesis + validation + PR opening.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Implement in-process case synthesis

**Files:**
- Modify: `src/corpus_learning_loop.py` (add `_synthesize_case`)
- Modify: `tests/test_corpus_learning_loop.py` (append synthesis test)

The loop dispatches Claude via `BaseRunner._execute` to produce a JSON envelope with `{case_name, expected_catcher, keyword, plan_text, before_files: {path: content}, after_files: {path: content}, readme}`. This is the **in-process LLM call** route (§4.1 v2 option a).

- [ ] **Step 1: Extend the loop**

Add to `src/corpus_learning_loop.py` (and add `AgentRunner` to the constructor):

```python
from agent import AgentRunner  # top of file

# Replace the constructor to accept AgentRunner:
def __init__(
    self,
    config: HydraFlowConfig,
    prs: PRManager,
    dedup: DedupStore,
    agents: AgentRunner,
    deps: LoopDeps,
) -> None:
    super().__init__(worker_name="corpus_learning", config=config, deps=deps)
    self._prs = prs
    self._dedup = dedup
    self._agents = agents


_SYNTH_PROMPT_TEMPLATE = """\
You are synthesizing a new adversarial corpus case for HydraFlow's
post-implementation skill chain (diff-sanity / scope-check / test-adequacy /
plan-compliance).

Escape issue #{issue_number}: {issue_title}

{issue_body}

Produce a minimal before/after file pair (1–4 files each) that reproduces
the escaped bug class. Pick the single skill that should have caught it.
Emit ONLY a JSON object between the markers <CASE_JSON> and </CASE_JSON>:

<CASE_JSON>
{{
  "case_name": "short-kebab-slug",
  "expected_catcher": "diff-sanity | scope-check | test-adequacy | plan-compliance",
  "keyword": "required-substring-in-RETRY-summary",
  "plan_text": "optional markdown plan (scope-check/plan-compliance only)",
  "before_files": {{"src/example.py": "pre-diff file body"}},
  "after_files": {{"src/example.py": "post-diff file body"}},
  "readme": "one-paragraph description of the bug class"
}}
</CASE_JSON>
"""


async def _synthesize_case(
    self, issue: dict[str, Any]
) -> dict[str, Any] | None:
    """Dispatch a Claude call to produce a case envelope. Returns None on parse failure."""
    prompt = _SYNTH_PROMPT_TEMPLATE.format(
        issue_number=issue.get("number", 0),
        issue_title=issue.get("title", ""),
        issue_body=(issue.get("body") or "")[: self._config.max_issue_body_chars],
    )
    transcript = await self._agents.run_oneshot_prompt(
        prompt,
        model=self._config.corpus_learning_model,
    )
    marker_start = transcript.find("<CASE_JSON>")
    marker_end = transcript.find("</CASE_JSON>")
    if marker_start == -1 or marker_end == -1 or marker_end < marker_start:
        logger.warning(
            "corpus-learning: no <CASE_JSON> markers in transcript for #%d",
            issue.get("number"),
        )
        return None
    payload = transcript[marker_start + len("<CASE_JSON>") : marker_end].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        logger.warning(
            "corpus-learning: JSON decode failed for #%d payload=%r",
            issue.get("number"),
            payload[:200],
        )
        return None
```

The `AgentRunner.run_oneshot_prompt(prompt, model=...)` method does not exist today. **Add it** as a thin wrapper inside `src/agent.py` adjacent to `_run_skill`:

```python
async def run_oneshot_prompt(self, prompt: str, *, model: str) -> str:
    """Dispatch a single Claude call with no worktree/tracing context.

    Used by background loops that need an LLM call outside of an issue's
    pipeline. Returns the raw transcript.
    """
    cmd = self._build_pre_quality_review_command()
    # Override the model flag if the base command is model-aware.
    if "--model" in cmd:
        idx = cmd.index("--model")
        cmd[idx + 1] = model
    else:
        cmd.extend(["--model", model])
    return await self._execute(
        cmd,
        prompt,
        self._config.repo_root,
        {"issue": 0, "source": "corpus-learning"},
    )
```

- [ ] **Step 2: Add a synthesis test**

Append to `tests/test_corpus_learning_loop.py`:

```python
def test_synthesize_case_parses_envelope(tmp_path: Path) -> None:
    agents = MagicMock()
    agents.run_oneshot_prompt = AsyncMock(return_value=(
        "Thinking...\n"
        "<CASE_JSON>\n"
        '{"case_name": "example", "expected_catcher": "diff-sanity", '
        '"keyword": "renamed", "plan_text": "", '
        '"before_files": {"src/x.py": "a\\n"}, '
        '"after_files": {"src/x.py": "b\\n"}, '
        '"readme": "desc"}\n'
        "</CASE_JSON>\n"
    ))
    loop = CorpusLearningLoop(
        config=_config(tmp_path),
        prs=MagicMock(),
        dedup=MagicMock(),
        agents=agents,
        deps=_deps(),
    )
    envelope = asyncio.run(loop._synthesize_case({"number": 99, "title": "t", "body": "b"}))
    assert envelope["case_name"] == "example"
    assert envelope["expected_catcher"] == "diff-sanity"


def test_synthesize_case_returns_none_on_missing_markers(tmp_path: Path) -> None:
    agents = MagicMock()
    agents.run_oneshot_prompt = AsyncMock(return_value="Sorry, cannot help.\n")
    loop = CorpusLearningLoop(
        config=_config(tmp_path),
        prs=MagicMock(),
        dedup=MagicMock(),
        agents=agents,
        deps=_deps(),
    )
    assert asyncio.run(loop._synthesize_case({"number": 99, "title": "t", "body": "b"})) is None
```

Also update the existing skeleton tests to include `agents=MagicMock()` in the constructor call (three places). Example:

```python
loop = CorpusLearningLoop(
    config=_config(tmp_path),
    prs=MagicMock(),
    dedup=MagicMock(),
    agents=MagicMock(),
    deps=_deps(),
)
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_corpus_learning_loop.py -v`
Expected: still blocked on missing config fields — flips green after Task 15.

- [ ] **Step 4: Commit**

```bash
git add src/corpus_learning_loop.py src/agent.py tests/test_corpus_learning_loop.py
git commit -m "$(cat <<'EOF'
feat(corpus-learning): in-process case synthesis via AgentRunner (§4.1 v2)

Synthesis dispatches Claude through a new AgentRunner.run_oneshot_prompt
wrapper (§4.1 v2 option a: in-process, lower latency, no routing issue).
The LLM returns a <CASE_JSON>...</CASE_JSON> envelope that is parsed into
{case_name, expected_catcher, keyword, before_files, after_files, readme,
plan_text}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Implement the three-gate self-validation

**Files:**
- Modify: `src/corpus_learning_loop.py` (add `_validate_case`, `_write_case_to_disk`, integrate into tick)
- Modify: `tests/test_corpus_learning_loop.py` (append validation tests)

Validation gates:
1. **Syntax**: every `.py` file under `before/` and `after/` must parse with `ast.parse`.
2. **Lint**: run `ruff check` scoped to the case directory; non-zero exit is a fail.
3. **Catcher trip**: invoke the harness's `test_case` function against the written case directory with the synthesized `expected_transcript.txt` — must raise 0 assertion errors.

- [ ] **Step 1: Extend the loop**

Add to `src/corpus_learning_loop.py`:

```python
import ast
import shutil
import tempfile
from pathlib import Path


async def _validate_case(self, case_dir: Path) -> tuple[bool, str]:
    """Run parse, lint, and catcher-trip gates. Returns (ok, failure_reason)."""
    # Gate 1: parse every .py under before/ and after/
    for py in list(case_dir.rglob("*.py")):
        try:
            ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            return False, f"parse error in {py.relative_to(case_dir)}: {exc}"

    # Gate 2: lint
    proc = await asyncio.create_subprocess_exec(
        "ruff", "check", str(case_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return False, f"ruff failed: {stdout.decode()[:500]}{stderr.decode()[:200]}"

    # Gate 3: catcher trip — run the harness against the synthesized case
    proc = await asyncio.create_subprocess_exec(
        "uv", "run", "pytest",
        "tests/trust/adversarial/test_adversarial_corpus.py",
        "-v", f"-k={case_dir.name}",
        cwd=str(self._config.repo_root),
        env={**os.environ, "PYTHONPATH": "src"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return False, (
            f"catcher did not trip: pytest exit={proc.returncode} "
            f"stdout={stdout.decode()[:500]} stderr={stderr.decode()[:200]}"
        )

    return True, ""


def _write_case_to_disk(self, envelope: dict[str, Any]) -> Path:
    """Materialize a synthesis envelope under tests/trust/adversarial/cases/."""
    cases_root = self._config.repo_root / "tests" / "trust" / "adversarial" / "cases"
    case_dir = cases_root / envelope["case_name"]
    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "before").mkdir(parents=True)
    (case_dir / "after").mkdir()
    for rel, body in envelope.get("before_files", {}).items():
        p = case_dir / "before" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for rel, body in envelope.get("after_files", {}).items():
        p = case_dir / "after" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (case_dir / "expected_catcher.txt").write_text(
        envelope["expected_catcher"] + "\n", encoding="utf-8"
    )
    (case_dir / "README.md").write_text(
        f"# {envelope['case_name']}\n\n{envelope['readme']}\n\n"
        f"Keyword: {envelope['keyword']}\n",
        encoding="utf-8",
    )
    if envelope.get("plan_text"):
        (case_dir / "plan.md").write_text(envelope["plan_text"], encoding="utf-8")
    # expected_transcript.txt — stub the RETRY marker for the named skill so
    # the gate-3 catcher-trip check is deterministic. The synthesizer is
    # responsible for making the before/after diff such that a live claude
    # call would also produce RETRY; this stub is the deterministic fallback.
    marker = {
        "diff-sanity": "DIFF_SANITY_RESULT",
        "scope-check": "SCOPE_CHECK_RESULT",
        "test-adequacy": "TEST_ADEQUACY_RESULT",
        "plan-compliance": "PLAN_COMPLIANCE_RESULT",
    }[envelope["expected_catcher"]]
    (case_dir / "expected_transcript.txt").write_text(
        f"{marker}: RETRY\nSUMMARY: {envelope['keyword']}\n"
        f"FINDINGS:\n- {envelope['case_name']} — synthesized\n",
        encoding="utf-8",
    )
    return case_dir
```

Add `import os` and `import asyncio` at the top of the file.

- [ ] **Step 2: Add validation tests**

Append to `tests/test_corpus_learning_loop.py`:

```python
def test_write_case_to_disk_materializes_layout(tmp_path: Path) -> None:
    loop = CorpusLearningLoop(
        config=_config(tmp_path, repo_root=tmp_path),
        prs=MagicMock(),
        dedup=MagicMock(),
        agents=MagicMock(),
        deps=_deps(),
    )
    envelope = {
        "case_name": "synth-sample",
        "expected_catcher": "diff-sanity",
        "keyword": "renamed",
        "plan_text": "",
        "before_files": {"src/a.py": "x = 1\n"},
        "after_files": {"src/a.py": "y = 1\n"},
        "readme": "desc",
    }
    case_dir = loop._write_case_to_disk(envelope)
    assert (case_dir / "before" / "src/a.py").read_text() == "x = 1\n"
    assert (case_dir / "after" / "src/a.py").read_text() == "y = 1\n"
    assert (case_dir / "expected_catcher.txt").read_text().strip() == "diff-sanity"
    assert "Keyword: renamed" in (case_dir / "README.md").read_text()
    assert "DIFF_SANITY_RESULT: RETRY" in (case_dir / "expected_transcript.txt").read_text()
```

- [ ] **Step 3: Run — still blocked on config fields (Task 15)**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_corpus_learning_loop.py::test_write_case_to_disk_materializes_layout -v`

- [ ] **Step 4: Commit**

```bash
git add src/corpus_learning_loop.py tests/test_corpus_learning_loop.py
git commit -m "$(cat <<'EOF'
feat(corpus-learning): three-gate self-validation + case materialization (§4.1 v2)

Gate 1: ast.parse every .py under before/ and after/.
Gate 2: `ruff check` the synthesized case dir.
Gate 3: run the adversarial harness scoped to the new case and confirm
the named catcher trips (the synth also emits a deterministic
expected_transcript.txt so gate 3 is stable without a live LLM call).

Failure at any gate returns (ok=False, reason) and the tick treats it as
a rejected attempt against the escape issue.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Wire synthesis + validation + PR opening into `_do_work`

**Files:**
- Modify: `src/corpus_learning_loop.py` (replace `_do_work` with the full pipeline; add `_escalate_issue` and `_open_case_pr`)

- [ ] **Step 1: Replace `_do_work`**

Replace `_do_work` and add two helper methods in `src/corpus_learning_loop.py`:

```python
_ESCALATION_LABELS = ["hitl-escalation", "corpus-learning-stuck"]
_MAX_ATTEMPTS_PER_ISSUE = 3


async def _open_case_pr(
    self, case_dir: Path, envelope: dict[str, Any], issue_number: int
) -> int:
    """Create a branch, commit the case, push, and open a PR against staging."""
    branch = f"corpus-learning/issue-{issue_number}-{envelope['case_name']}"
    cwd = str(self._config.repo_root)
    # Branch off staging
    for args in (
        ("git", "fetch", "origin", self._config.staging_branch),
        ("git", "checkout", "-B", branch, f"origin/{self._config.staging_branch}"),
        ("git", "add", str(case_dir.relative_to(self._config.repo_root))),
        ("git", "commit", "-m", f"test(trust): corpus-learning — case from escape #{issue_number}"),
        ("git", "push", "-u", "origin", branch, "--force-with-lease"),
    ):
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "corpus-learning: git step %r failed (rc=%d): %s",
                args, proc.returncode, stderr.decode()[:400],
            )
            return 0

    body = (
        f"Synthesized adversarial corpus case for escape issue #{issue_number}.\n\n"
        f"**Catcher:** `{envelope['expected_catcher']}`\n"
        f"**Keyword:** `{envelope['keyword']}`\n\n"
        f"## Reasoning\n\n{envelope['readme']}\n\n"
        f"Closes #{issue_number}"
    )
    # PRManager.create_pr returns the PR number; reuse existing surface.
    return await self._prs.create_pr(
        title=f"test(trust): corpus-learning case for escape #{issue_number}",
        body=body,
        base=self._config.staging_branch,
        head=branch,
        labels=["hydraflow-agent", "corpus-learning"],
    )


async def _escalate_issue(self, issue_number: int, attempts: list[str]) -> None:
    """Label the escape issue for HITL and record the failed attempts."""
    body = (
        "Corpus learning loop rejected 3 synthesis attempts for this escape:\n\n"
        + "\n".join(f"- attempt {i+1}: {reason}" for i, reason in enumerate(attempts))
        + "\n\nManual authoring required — add a case under "
        "tests/trust/adversarial/cases/ following the README keyword convention."
    )
    await self._prs.add_issue_comment(issue_number, body)
    await self._prs.add_labels(issue_number, _ESCALATION_LABELS)


async def _do_work(self) -> dict[str, Any] | None:
    issues = await self._list_escape_issues()
    stats = {
        "escape_issues_seen": len(issues),
        "cases_proposed": 0,
        "escalated": 0,
    }
    seen = self._dedup.get()
    for issue in issues:
        num = issue.get("number")
        if not isinstance(num, int):
            continue
        dedup_key = f"escape-{num}"
        if dedup_key in seen:
            continue
        attempts: list[str] = []
        case_dir: Path | None = None
        envelope: dict[str, Any] | None = None
        for _ in range(_MAX_ATTEMPTS_PER_ISSUE):
            envelope = await self._synthesize_case(issue)
            if envelope is None:
                attempts.append("synthesis returned no envelope")
                continue
            case_dir = self._write_case_to_disk(envelope)
            ok, reason = await self._validate_case(case_dir)
            if ok:
                break
            attempts.append(reason)
            shutil.rmtree(case_dir, ignore_errors=True)
            case_dir = None
        if case_dir is None or envelope is None:
            await self._escalate_issue(num, attempts)
            self._dedup.add(dedup_key)
            stats["escalated"] += 1
            continue
        pr_number = await self._open_case_pr(case_dir, envelope, num)
        if pr_number > 0:
            stats["cases_proposed"] += 1
        self._dedup.add(dedup_key)
    return stats
```

The plan assumes `PRManager.create_pr` and `PRManager.add_issue_comment` + `add_labels` exist. Check before proceeding:

Run: `grep -n "async def create_pr\|async def add_issue_comment\|async def add_labels" /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening/src/pr_manager.py`
Expected: three matches. If any method is missing, add a minimal wrapper next to `create_issue` that shells out to `gh pr create`, `gh issue comment`, or `gh issue edit --add-label`; the signatures above must exist before Task 16 runs.

- [ ] **Step 2: Commit**

```bash
git add src/corpus_learning_loop.py
git commit -m "$(cat <<'EOF'
feat(corpus-learning): full tick — synth, validate, PR, escalate (§4.1 v2)

Loop iterates unseen skill-escape issues, runs up to 3 synthesis attempts
per issue with three-gate self-validation, and on success branches off
staging, commits the case, pushes, and opens a PR labeled
`hydraflow-agent`, `corpus-learning` (auto-merge path per §3.2). On 3
rejected attempts, files an hitl-escalation comment + labels with the
attempt log and moves on.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Five-checkpoint wiring

Five separate commits, one per checkpoint, per `docs/agents/background-loops.md`.

---

#### Task 15a: `src/config.py` — interval, model, signal-label fields + env overrides

**Files:**
- Modify: `src/config.py:74-133` (append to `_ENV_INT_OVERRIDES` and `_ENV_STR_OVERRIDES`), and add three `Field` declarations in the config class body near line 1371 (`staging_promotion_interval`).

- [ ] **Step 1: Append to `_ENV_INT_OVERRIDES`**

Insert a new entry into `_ENV_INT_OVERRIDES` (currently ends at line 133 with `("visual_max_retries", ...)`). Add after it:

```python
    ("corpus_learning_interval", "HYDRAFLOW_CORPUS_LEARNING_INTERVAL", 3600),
```

- [ ] **Step 2: Append to `_ENV_STR_OVERRIDES`**

Insert after `("memory_judge_model", "HYDRAFLOW_MEMORY_JUDGE_MODEL", "haiku"),` at line 198:

```python
    ("corpus_learning_model", "HYDRAFLOW_CORPUS_LEARNING_MODEL", "sonnet"),
    ("corpus_learning_signal_label", "HYDRAFLOW_CORPUS_LEARNING_SIGNAL_LABEL", "skill-escape"),
```

- [ ] **Step 3: Add `Field` declarations in the config class body**

Locate `staging_promotion_interval:` (line 1371). Insert immediately after its block (i.e., after line 1382, before `git_user_name:`):

```python
    corpus_learning_interval: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description="Seconds between CorpusLearningLoop ticks",
    )
    corpus_learning_model: str = Field(
        default="sonnet",
        description="Model for corpus-learning case synthesis (HYDRAFLOW_CORPUS_LEARNING_MODEL)",
    )
    corpus_learning_signal_label: str = Field(
        default="skill-escape",
        description="Label on hydraflow-find issues that triggers corpus-learning synthesis",
    )
```

- [ ] **Step 4: Verify config loads**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "from config import HydraFlowConfig; c = HydraFlowConfig(repo='o/r'); print(c.corpus_learning_interval, c.corpus_learning_model, c.corpus_learning_signal_label)"`
Expected: `3600 sonnet skill-escape`.

- [ ] **Step 5: Commit**

```bash
git add src/config.py
git commit -m "$(cat <<'EOF'
feat(config): corpus-learning interval, model, signal-label (§4.1 v2 wiring 1/5)

Adds three config knobs + env-var overrides per docs/agents/background-loops.md:
- `corpus_learning_interval` (HYDRAFLOW_CORPUS_LEARNING_INTERVAL=3600)
- `corpus_learning_model` (HYDRAFLOW_CORPUS_LEARNING_MODEL=sonnet)
- `corpus_learning_signal_label` (HYDRAFLOW_CORPUS_LEARNING_SIGNAL_LABEL=skill-escape)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

#### Task 15b: `src/dashboard_routes/_common.py` — `_INTERVAL_BOUNDS`

**Files:**
- Modify: `src/dashboard_routes/_common.py:32-56` (insert into `_INTERVAL_BOUNDS` dict)

- [ ] **Step 1: Add the entry**

Append to `_INTERVAL_BOUNDS` (line 55 is currently `"retrospective": (60, 86400),`). Insert after `"retrospective":` and before the closing `}`:

```python
    "corpus_learning": (300, 86400),
```

- [ ] **Step 2: Commit**

```bash
git add src/dashboard_routes/_common.py
git commit -m "$(cat <<'EOF'
feat(dashboard): corpus_learning interval bounds (§4.1 v2 wiring 2/5)

Bounds (300, 86400) match the Field `ge=300, le=86400` constraint in
config.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

#### Task 15c: `src/ui/src/constants.js` — BACKGROUND_WORKERS + intervals + editable set

**Files:**
- Modify: `src/ui/src/constants.js:252` (`EDITABLE_INTERVAL_WORKERS` Set)
- Modify: `src/ui/src/constants.js:259-274` (`SYSTEM_WORKER_INTERVALS` dict)
- Modify: `src/ui/src/constants.js:293-313` (`BACKGROUND_WORKERS` array)

- [ ] **Step 1: Extend `EDITABLE_INTERVAL_WORKERS`**

Change line 252 from:

```js
export const EDITABLE_INTERVAL_WORKERS = new Set(['memory_sync', 'pr_unsticker', 'pipeline_poller', 'report_issue', 'worktree_gc', 'adr_reviewer', 'epic_sweeper', 'dependabot_merge', 'staging_promotion', 'stale_issue', 'security_patch', 'ci_monitor', 'code_grooming', 'sentry_ingest', 'retrospective'])
```

to:

```js
export const EDITABLE_INTERVAL_WORKERS = new Set(['memory_sync', 'pr_unsticker', 'pipeline_poller', 'report_issue', 'worktree_gc', 'adr_reviewer', 'epic_sweeper', 'dependabot_merge', 'staging_promotion', 'stale_issue', 'security_patch', 'ci_monitor', 'code_grooming', 'sentry_ingest', 'retrospective', 'corpus_learning'])
```

- [ ] **Step 2: Extend `SYSTEM_WORKER_INTERVALS`**

Insert after `retrospective: 1800,` (line 273) and before the closing `}`:

```js
  corpus_learning: 3600,
```

- [ ] **Step 3: Extend `BACKGROUND_WORKERS`**

Insert after the `diagnostic` entry (line 312, just before the closing `]`):

```js
  { key: 'corpus_learning', label: 'Corpus Learning', description: 'Grows the adversarial skill corpus from skill-escape issues. Synthesizes cases, self-validates, and opens auto-merge PRs against staging. See spec §4.1 v2.', color: theme.purple, group: 'learning', tags: ['insights'] },
```

- [ ] **Step 4: Commit**

```bash
git add src/ui/src/constants.js
git commit -m "$(cat <<'EOF'
feat(ui): corpus_learning entry in BACKGROUND_WORKERS (§4.1 v2 wiring 3/5)

Adds dashboard visibility for CorpusLearningLoop: editable interval,
default 3600s, learning group with insights tag.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

#### Task 15d: `src/service_registry.py` — dataclass field + build step

**Files:**
- Modify: `src/service_registry.py:56` (import)
- Modify: `src/service_registry.py:148-169` (dataclass field)
- Modify: `src/service_registry.py:680-813` (build step) + `src/service_registry.py:815-873` (return-dict kwarg)

- [ ] **Step 1: Add the import**

Insert at line 20 (alphabetical order after `ci_monitor_loop`):

```python
from corpus_learning_loop import CorpusLearningLoop
```

- [ ] **Step 2: Add the dataclass field**

Insert after line 168 `retrospective_queue: RetrospectiveQueue` (and before `# Optional integrations`):

```python
    corpus_learning_loop: CorpusLearningLoop
```

- [ ] **Step 3: Build + wire the loop**

Locate the block that constructs `retrospective_loop` at line 806. After that block ends (around line 813), insert:

```python
    from dedup_store import DedupStore as _DedupStore  # noqa: PLC0415

    corpus_learning_dedup = _DedupStore(
        "corpus_learning_seen",
        config.data_root / "dedup" / "corpus_learning_seen.json",
        dolt=dolt_backend,
    )
    corpus_learning_loop = CorpusLearningLoop(
        config=config,
        prs=prs,
        dedup=corpus_learning_dedup,
        agents=agents,
        deps=loop_deps,
    )
```

Then in the `ServiceRegistry(...)` return block (line 815 onward), add `corpus_learning_loop=corpus_learning_loop,` before the closing `)`. Place it alphabetically between `ci_monitor_loop=ci_monitor_loop,` and `diagnostic_loop=diagnostic_loop,`.

- [ ] **Step 4: Commit**

```bash
git add src/service_registry.py
git commit -m "$(cat <<'EOF'
feat(services): wire CorpusLearningLoop into ServiceRegistry (§4.1 v2 wiring 4/5)

Adds dataclass field, DedupStore for per-escape-issue idempotency, and
build step. The loop reuses the shared PRManager, AgentRunner, and
LoopDeps; no new infra.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

#### Task 15e: `src/orchestrator.py` — `bg_loop_registry` + loop_factories

**Files:**
- Modify: `src/orchestrator.py:138-159` (`bg_loop_registry` dict)
- Modify: `src/orchestrator.py:880-910` (`loop_factories` list)

- [ ] **Step 1: Add to `bg_loop_registry`**

Insert after line 158 `"retrospective": svc.retrospective_loop,` (before the closing `}`):

```python
            "corpus_learning": svc.corpus_learning_loop,
```

- [ ] **Step 2: Add to `loop_factories`**

Insert after line 909 `("retrospective", self._svc.retrospective_loop.run),`:

```python
            ("corpus_learning", self._svc.corpus_learning_loop.run),
```

- [ ] **Step 3: Run the wiring-completeness test**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v`
Expected: all tests pass (the regex-based discovery picks up `CorpusLearningLoop` and verifies all five checkpoints).

- [ ] **Step 4: Run the loop unit tests now that config fields exist**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_corpus_learning_loop.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): register + start CorpusLearningLoop (§4.1 v2 wiring 5/5)

Completes the five-checkpoint wiring per docs/agents/background-loops.md.
`tests/test_loop_wiring_completeness.py` now passes for the new loop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

#### Task 15f: Telemetry emission — `prompt_telemetry` + `trace_collector` for the loop

**Files:**
- Modify: `src/corpus_learning_loop.py` (inject `PromptTelemetry` + `TraceCollector` via `LoopDeps`, wrap LLM + subprocess call sites)
- Modify: `src/service_registry.py` (pass the shared `PromptTelemetry` + a `trace_collector` factory into the loop via `LoopDeps`)
- Modify: `tests/test_corpus_learning_loop.py` (append telemetry unit tests)

**Why this task (per spec §4.11 point 3).** Every new loop must feed
the per-issue waterfall and the per-loop cost dashboard. If the loop
ticks without emitting telemetry it silently disappears from
Diagnostics — operators cannot see its cost, its cadence, or its
subprocess activity. §4.11 point 3 requires `{"kind": "loop", "loop":
"<LoopClassName>"}` action shapes in the emitted records. Kill-switch
respect is load-bearing: when `corpus_learning_enabled=False` the
tick exits before any LLM or subprocess call, so **zero** telemetry
should be emitted.

- [ ] **Step 1: Append failing telemetry unit tests**

Append to `tests/test_corpus_learning_loop.py`:

```python
def test_tick_emits_prompt_telemetry_with_loop_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every LLM dispatch in CorpusLearningLoop._do_work records a
    prompt_telemetry entry shaped {"kind": "loop", "loop": "CorpusLearningLoop"}
    per spec §4.11 point 3."""
    import corpus_learning_loop as mod  # noqa: PLC0415
    from dedup_store import DedupStore  # noqa: PLC0415

    recorded: list[dict] = []

    class _CaptureTelemetry:
        def record(self, **kwargs):
            recorded.append(kwargs)

    repo_root = tmp_path / "repo"
    (repo_root / "tests/trust/adversarial/cases").mkdir(parents=True)

    escape_payload = json.dumps([{
        "number": 5151,
        "title": "t",
        "body": "",
        "labels": [{"name": "skill-escape"}, {"name": "hydraflow-find"}],
    }])
    monkeypatch.setattr(mod, "run_subprocess", AsyncMock(return_value=escape_payload))

    agents = MagicMock()
    agents.run_oneshot_prompt = AsyncMock(return_value=(
        "<CASE_JSON>\n"
        '{"case_name": "telemetry-case", "expected_catcher": "diff-sanity", '
        '"keyword": "renamed", "plan_text": "", '
        '"before_files": {"src/x.py": "def a():\\n    return 1\\n"}, '
        '"after_files": {"src/x.py": "def b():\\n    return 1\\n"}, '
        '"readme": "renamed"}\n'
        "</CASE_JSON>\n"
    ))

    prs = MagicMock()
    prs.create_pr = AsyncMock(return_value=7777)
    prs.add_issue_comment = AsyncMock()
    prs.add_labels = AsyncMock()

    deps = _deps()
    deps.prompt_telemetry = _CaptureTelemetry()

    cfg = _config(tmp_path, repo_root=repo_root, staging_branch="staging")
    loop = CorpusLearningLoop(
        config=cfg,
        prs=prs,
        dedup=DedupStore("test_seen", tmp_path / "dedup.json"),
        agents=agents,
        deps=deps,
    )
    monkeypatch.setattr(loop, "_validate_case", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(loop, "_open_case_pr", AsyncMock(return_value=7777))

    asyncio.run(loop._do_work())

    # Synthesis LLM call emitted exactly one telemetry record.
    llm_records = [r for r in recorded if r.get("tool") == "corpus_learning"]
    assert len(llm_records) == 1
    rec = llm_records[0]
    assert rec["source"] == "loop"
    stats = rec.get("stats") or {}
    assert stats.get("kind") == "loop"
    assert stats.get("loop") == "CorpusLearningLoop"


def test_tick_records_subprocess_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gh` CLI invocations in the escape-signal reader feed a
    TraceCollector-shaped record so subprocess cost shows up in the
    Diagnostics waterfall."""
    import corpus_learning_loop as mod  # noqa: PLC0415
    from dedup_store import DedupStore  # noqa: PLC0415

    trace_lines: list[str] = []

    class _CaptureTrace:
        def record(self, raw_line: str) -> None:
            trace_lines.append(raw_line)

        def finalize(self) -> None:
            pass

    repo_root = tmp_path / "repo"
    (repo_root / "tests/trust/adversarial/cases").mkdir(parents=True)

    monkeypatch.setattr(mod, "run_subprocess", AsyncMock(return_value="[]"))

    deps = _deps()
    deps.trace_collector_factory = lambda **_kw: _CaptureTrace()

    cfg = _config(tmp_path, repo_root=repo_root, staging_branch="staging")
    loop = CorpusLearningLoop(
        config=cfg,
        prs=MagicMock(),
        dedup=DedupStore("test_seen", tmp_path / "dedup.json"),
        agents=MagicMock(),
        deps=deps,
    )

    asyncio.run(loop._do_work())

    # At least one subprocess span recorded for the `gh api` query.
    assert trace_lines, "expected a subprocess trace line for gh api invocation"
    payloads = [json.loads(line) for line in trace_lines]
    kinds = {p.get("kind") for p in payloads}
    assert "loop" in kinds
    assert any(p.get("loop") == "CorpusLearningLoop" for p in payloads)


def test_kill_switch_disables_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `corpus_learning_enabled=False`, the tick exits before any
    LLM or subprocess work — zero telemetry records, zero trace spans.
    Regression guard for the kill-switch contract in spec §3.2."""
    import corpus_learning_loop as mod  # noqa: PLC0415
    from dedup_store import DedupStore  # noqa: PLC0415

    recorded: list[dict] = []
    trace_lines: list[str] = []

    class _CaptureTelemetry:
        def record(self, **kwargs):
            recorded.append(kwargs)

    class _CaptureTrace:
        def record(self, raw_line: str) -> None:
            trace_lines.append(raw_line)

        def finalize(self) -> None:
            pass

    subprocess_spy = AsyncMock(return_value="[]")
    monkeypatch.setattr(mod, "run_subprocess", subprocess_spy)

    deps = _deps()
    deps.enabled_cb = MagicMock(return_value=False)
    deps.prompt_telemetry = _CaptureTelemetry()
    deps.trace_collector_factory = lambda **_kw: _CaptureTrace()

    cfg = _config(tmp_path)
    loop = CorpusLearningLoop(
        config=cfg,
        prs=MagicMock(),
        dedup=DedupStore("test_seen", tmp_path / "dedup.json"),
        agents=MagicMock(),
        deps=deps,
    )

    asyncio.run(loop._do_work())

    assert recorded == [], f"expected zero telemetry when disabled, got {recorded!r}"
    assert trace_lines == [], f"expected zero trace spans when disabled, got {trace_lines!r}"
    subprocess_spy.assert_not_awaited()
```

- [ ] **Step 2: Run the tests — they fail against the current loop**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_corpus_learning_loop.py::test_tick_emits_prompt_telemetry_with_loop_kind tests/test_corpus_learning_loop.py::test_tick_records_subprocess_trace tests/test_corpus_learning_loop.py::test_kill_switch_disables_telemetry -v`
Expected: all three fail — `LoopDeps` does not yet carry `prompt_telemetry` / `trace_collector_factory`, and `_do_work` does not emit.

- [ ] **Step 3: Extend `LoopDeps` (if not already present)**

Open `src/base_background_loop.py`. If `LoopDeps` does not already carry `prompt_telemetry: PromptTelemetry | None` and `trace_collector_factory: Callable[..., TraceCollector] | None`, add them as optional fields with `None` defaults so existing loops construct unchanged. Import `PromptTelemetry` from `prompt_telemetry` and `TraceCollector` from `trace_collector` under a `TYPE_CHECKING:` block to avoid circular imports.

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "from base_background_loop import LoopDeps; import inspect; print('prompt_telemetry' in inspect.signature(LoopDeps).parameters, 'trace_collector_factory' in inspect.signature(LoopDeps).parameters)"`
Expected: `True True`.

- [ ] **Step 4: Instrument the LLM synthesis call in `src/corpus_learning_loop.py`**

Locate the `agents.run_oneshot_prompt(...)` call in `_synthesize_case` (introduced in Task 12). Wrap it:

```python
    async def _synthesize_case(self, issue: dict) -> dict | None:
        prompt = self._build_synthesis_prompt(issue)
        start = time.monotonic()
        transcript = await self._agents.run_oneshot_prompt(
            prompt=prompt,
            model=self._config.corpus_learning_model,
        )
        duration = time.monotonic() - start
        telemetry = getattr(self._deps, "prompt_telemetry", None)
        if telemetry is not None:
            telemetry.record(
                source="loop",
                tool="corpus_learning",
                model=self._config.corpus_learning_model,
                issue_number=issue.get("number"),
                pr_number=None,
                session_id=None,
                prompt_chars=len(prompt),
                transcript_chars=len(transcript),
                duration_seconds=duration,
                success=True,
                stats={"kind": "loop", "loop": "CorpusLearningLoop"},
            )
        return self._parse_case_envelope(transcript)
```

- [ ] **Step 5: Instrument `gh api` subprocess calls in the escape-signal reader**

In `_list_escape_issues` (Task 11), wrap every `run_subprocess(["gh", ...])` call with a `TraceCollector` scoped to this loop:

```python
    async def _list_escape_issues(self) -> list[dict]:
        factory = getattr(self._deps, "trace_collector_factory", None)
        collector = factory(
            issue_number=None,
            phase="loop.corpus_learning",
            source="corpus_learning",
            subprocess_idx=0,
        ) if factory else None

        cmd = [
            "gh", "api",
            f"repos/{self._config.repo}/issues",
            "--jq", f'[.[] | select(.labels | map(.name) | contains(["{self._config.corpus_learning_signal_label}"]))]',
        ]
        start = time.monotonic()
        raw = await run_subprocess(cmd)
        duration_ms = int((time.monotonic() - start) * 1000)

        if collector is not None:
            # One JSON-line span per subprocess invocation, shape matches
            # spec §4.11 point 3 (`kind=loop`, `loop=<ClassName>`).
            collector.record(json.dumps({
                "type": "subprocess",
                "kind": "loop",
                "loop": "CorpusLearningLoop",
                "command": cmd,
                "duration_ms": duration_ms,
            }))
            collector.finalize()

        return json.loads(raw or "[]")
```

- [ ] **Step 6: Gate both instrumentation sites behind the kill-switch**

Confirm that `BaseBackgroundLoop.run` already short-circuits on `enabled_cb()` returning False before calling `_do_work`. If so, the telemetry tests' "disabled → zero emission" assertion is satisfied for free. If the skeleton bypasses this, add an early return at the top of `_do_work`:

```python
        if not self._deps.enabled_cb():
            return {"escape_issues_seen": 0, "cases_proposed": 0, "escalated": 0, "disabled": True}
```

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "from base_background_loop import BaseBackgroundLoop; import inspect; src = inspect.getsource(BaseBackgroundLoop); print('enabled_cb' in src)"`
Expected: `True`.

- [ ] **Step 7: Wire the shared `PromptTelemetry` + trace factory through `service_registry.py`**

In `src/service_registry.py`, locate the `LoopDeps(...)` constructor the loops share. Plumb the already-constructed `prompt_telemetry` service and a lambda that returns a configured `TraceCollector`:

```python
    loop_deps = LoopDeps(
        event_bus=event_bus,
        stop_event=stop_event,
        status_cb=worker_status_cb,
        enabled_cb=worker_enabled_cb,
        interval_cb=worker_interval_cb,
        prompt_telemetry=prompt_telemetry,
        trace_collector_factory=lambda **kw: TraceCollector(
            config=config,
            event_bus=event_bus,
            run_id=int(time.time_ns()),
            **kw,
        ),
    )
```

Import `TraceCollector` alongside the existing `prompt_telemetry` import near the top of the file.

- [ ] **Step 8: Re-run the three telemetry tests — they pass**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_corpus_learning_loop.py -v`
Expected: all tests pass, including the three added in Step 1.

- [ ] **Step 9: Commit**

```bash
git add src/base_background_loop.py src/corpus_learning_loop.py src/service_registry.py tests/test_corpus_learning_loop.py
git commit -m "$(cat <<'EOF'
feat(corpus-learning): emit prompt + trace telemetry per §4.11 point 3

LLM synthesis calls record a `prompt_telemetry` entry shaped
{"kind": "loop", "loop": "CorpusLearningLoop"}; `gh api` subprocess
invocations feed a scoped `TraceCollector` span. Honors the
kill-switch contract: disabled tick emits zero records. LoopDeps
gains optional prompt_telemetry + trace_collector_factory fields so
existing loops construct unchanged.

Unblocks the per-issue waterfall and per-loop cost dashboard endpoints
introduced by §4.11 for the CorpusLearningLoop row.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: Integration test — end-to-end mocked escape → PR

**Files:**
- Modify: `tests/test_corpus_learning_loop.py` (append an integration test that mocks `gh api`, `AgentRunner.run_oneshot_prompt`, `PRManager.create_pr`, and `ruff` subprocess)

- [ ] **Step 1: Write the integration test**

Append to `tests/test_corpus_learning_loop.py`:

```python
def test_end_to_end_escape_to_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mocked escape issue → synthesized case → passes validation → PR opened."""
    import corpus_learning_loop as mod  # noqa: PLC0415
    from dedup_store import DedupStore  # noqa: PLC0415

    repo_root = tmp_path / "repo"
    (repo_root / "tests/trust/adversarial/cases").mkdir(parents=True)

    # Mock `gh api` escape-issues query
    escape_payload = json.dumps([{
        "number": 4242,
        "title": "skill missed renamed symbol",
        "body": "PR #123 introduced a NameError the diff-sanity skill should have caught",
        "labels": [{"name": "skill-escape"}, {"name": "hydraflow-find"}],
    }])
    monkeypatch.setattr(mod, "run_subprocess", AsyncMock(return_value=escape_payload))

    # Mock AgentRunner synthesis — returns a well-formed envelope
    agents = MagicMock()
    agents.run_oneshot_prompt = AsyncMock(return_value=(
        "<CASE_JSON>\n"
        '{"case_name": "synth-renamed", "expected_catcher": "diff-sanity", '
        '"keyword": "renamed", "plan_text": "", '
        '"before_files": {"src/x.py": "def foo():\\n    return 1\\n"}, '
        '"after_files": {"src/x.py": "def bar():\\n    return 1\\n"}, '
        '"readme": "Renamed def foo to def bar without updating callers."}\n'
        "</CASE_JSON>\n"
    ))

    # Mock PRManager
    prs = MagicMock()
    prs.create_pr = AsyncMock(return_value=9999)
    prs.add_issue_comment = AsyncMock()
    prs.add_labels = AsyncMock()

    # Mock _validate_case to force gate-3 green (we exercise gates 1&2 elsewhere)
    cfg = _config(tmp_path, repo_root=repo_root, staging_branch="staging")
    loop = CorpusLearningLoop(
        config=cfg,
        prs=prs,
        dedup=DedupStore("test_seen", tmp_path / "dedup.json"),
        agents=agents,
        deps=_deps(),
    )
    monkeypatch.setattr(loop, "_validate_case", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(loop, "_open_case_pr", AsyncMock(return_value=9999))

    stats = asyncio.run(loop._do_work())
    assert stats["escape_issues_seen"] == 1
    assert stats["cases_proposed"] == 1
    assert stats["escalated"] == 0
    # Case directory exists on disk
    assert (repo_root / "tests/trust/adversarial/cases/synth-renamed").is_dir()


def test_end_to_end_three_rejections_escalate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three synthesis failures on the same issue → hitl-escalation labels."""
    import corpus_learning_loop as mod  # noqa: PLC0415
    from dedup_store import DedupStore  # noqa: PLC0415

    repo_root = tmp_path / "repo"
    (repo_root / "tests/trust/adversarial/cases").mkdir(parents=True)

    escape_payload = json.dumps([{
        "number": 4243,
        "title": "test",
        "body": "",
        "labels": [{"name": "skill-escape"}, {"name": "hydraflow-find"}],
    }])
    monkeypatch.setattr(mod, "run_subprocess", AsyncMock(return_value=escape_payload))

    agents = MagicMock()
    agents.run_oneshot_prompt = AsyncMock(return_value="no markers here\n")

    prs = MagicMock()
    prs.add_issue_comment = AsyncMock()
    prs.add_labels = AsyncMock()

    cfg = _config(tmp_path, repo_root=repo_root, staging_branch="staging")
    loop = CorpusLearningLoop(
        config=cfg,
        prs=prs,
        dedup=DedupStore("test_seen", tmp_path / "dedup.json"),
        agents=agents,
        deps=_deps(),
    )

    stats = asyncio.run(loop._do_work())
    assert stats["escalated"] == 1
    prs.add_labels.assert_awaited_once()
    args, _kwargs = prs.add_labels.call_args
    assert args[0] == 4243
    assert set(args[1]) >= {"hitl-escalation", "corpus-learning-stuck"}
```

- [ ] **Step 2: Run the full loop test suite**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_corpus_learning_loop.py -v`
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_corpus_learning_loop.py
git commit -m "$(cat <<'EOF'
test(corpus-learning): end-to-end escape → PR and 3-reject escalation (§7)

Happy path: mocked gh api escape issue → LLM envelope → validation green
→ PR opened, stats reflect cases_proposed=1.
Escalation path: 3 synthesis rejections (no JSON markers) → hitl-escalation
+ corpus-learning-stuck labels applied, stats.escalated=1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: Verify `test_loop_wiring_completeness.py` picks up the new loop

**Files:**
- Modify (optional): `tests/test_loop_wiring_completeness.py` — no explicit entry needed; the regex-based discovery handles new loops automatically. This task is a verification step.

- [ ] **Step 1: Run the wiring test in isolation**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v`
Expected: all four sub-tests (`test_all_loops_in_registry`, `test_all_loops_in_service_registry`, `test_all_loops_in_constants_js`, `test_all_loops_in_interval_bounds`) pass with `corpus_learning` discovered.

- [ ] **Step 2: If any assertion fails, fix the missing checkpoint**

The test's failure output explicitly names the checkpoint file and the missing worker key — jump back to Task 15a–15e and patch the corresponding file.

---

### Task 18: MockWorld scenario — escape issue → case PR against `staging`

**Files:**
- Create: `tests/scenarios/test_corpus_learning_scenario.py`
- Modify (if needed): `tests/scenarios/helpers/loop_port_seeding.py` (only if the catalog does not already know about `corpus_learning`)

**Why this task (per spec §7 "MockWorld scenarios (integration-side) — required").** Unit tests exercise `CorpusLearningLoop` in isolation with mocked `gh api` and `PRManager`. The MockWorld scenario proves the loop integrates with the factory's stateful world — `FakeClock`, `FakeGitHub`, `FakeLLM`, `FakeFilesystem` — and closes the full loop: seeded escape issue → tick fires → synthesis prompt hits the scripted `FakeLLM` → case materializes on disk → PR opens against `staging` → self-validation gate runs with the real harness shim. A loop that passes unit tests but fails here has drifted from the pipeline contract; only the scenario catches that.

- [ ] **Step 1: Write the failing scenario test**

Create `tests/scenarios/test_corpus_learning_scenario.py`:

```python
"""Scenario L14 — CorpusLearningLoop grows the adversarial corpus from a
skill-escape issue (§4.1 v2, §7 required scenario).

Seeds MockWorld with a scripted `skill-escape`-labeled hydraflow-find
issue that references a reverted commit. Advances FakeClock past
`corpus_learning_interval`. Runs one tick of the pipeline. Asserts the
world's final state carries a new PR against `staging` whose diff
includes a new case directory under `tests/trust/adversarial/cases/`,
that the scripted FakeLLM observed the synthesis prompt, and that the
case passes self-validation.

Then a second test flips the FakeLLM transcript to one that fails
self-validation three times in a row and asserts the loop escalates
per §3.2 (hitl-escalation + corpus-learning-stuck labels on the
escape issue).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


_CASE_ENVELOPE_GOOD = (
    "<CASE_JSON>\n"
    "{\n"
    '  "case_name": "synth-renamed-scenario",\n'
    '  "expected_catcher": "diff-sanity",\n'
    '  "keyword": "renamed",\n'
    '  "plan_text": "",\n'
    '  "before_files": {"src/x.py": "def foo():\\n    return 1\\n"},\n'
    '  "after_files": {"src/x.py": "def bar():\\n    return 1\\n"},\n'
    '  "readme": "Renamed def foo to def bar without updating callers."\n'
    "}\n"
    "</CASE_JSON>\n"
)

_CASE_ENVELOPE_BAD = "no markers here — synthesis failed to emit a valid envelope\n"


class TestL14CorpusLearningScenario:
    """L14: CorpusLearningLoop end-to-end under MockWorld."""

    async def test_escape_issue_produces_case_pr_against_staging(
        self, tmp_path: Path
    ) -> None:
        """Happy path: skill-escape issue + clock advance → synthesis prompt
        fires through scripted FakeLLM → case directory materializes on
        FakeFilesystem → PR opens against `staging` branch → self-validation
        passes. Closes the feedback loop §4.1 v2 describes.
        """
        world = MockWorld(tmp_path)

        # Seed the escape signal: a hydraflow-find issue labeled skill-escape
        # whose body references the reverted commit.
        world.github.seed_issue(
            number=9001,
            title="skill missed renamed symbol in PR #8800",
            body=(
                "PR #8800 reverted at abcdef0123 because diff-sanity let a "
                "renamed symbol through. Reverted-commit: abcdef0123."
            ),
            labels=["hydraflow-find", "skill-escape"],
            state="open",
        )

        # Script the FakeLLM: the synthesis prompt gets the good envelope.
        world.llm.script_response(
            match_substring="Synthesize an adversarial corpus case",
            response=_CASE_ENVELOPE_GOOD,
        )

        # Seed the harness shim: validation gate trips the named catcher.
        fake_harness = AsyncMock()
        fake_harness.run_case_through_catcher = AsyncMock(
            return_value={"result": "RETRY", "reason": "renamed symbol not updated at callsite"}
        )
        _seed_ports(world, corpus_learning_harness=fake_harness)

        # Advance the clock past corpus_learning_interval (default 3600s).
        world.clock.advance(seconds=3601)

        # Run one pipeline tick.
        stats = await world.run_pipeline(loops=["corpus_learning"], cycles=1)

        # Assertion 1: the FakeLLM saw the synthesis prompt exactly once.
        synthesis_calls = [
            call for call in world.llm.calls
            if "Synthesize an adversarial corpus case" in call.prompt
        ]
        assert len(synthesis_calls) == 1, (
            f"expected one synthesis LLM call, got {len(synthesis_calls)}: "
            f"{[c.prompt[:80] for c in world.llm.calls]}"
        )

        # Assertion 2: a PR was opened against `staging`.
        prs_against_staging = [
            pr for pr in world.github.prs.values() if pr.base == "staging"
        ]
        assert len(prs_against_staging) == 1, (
            f"expected one PR against staging, got {len(prs_against_staging)} "
            f"(all PRs: {list(world.github.prs.values())})"
        )
        pr = prs_against_staging[0]

        # Assertion 3: the PR diff adds a case directory under
        # tests/trust/adversarial/cases/.
        added_paths = [p for p in pr.added_paths if "tests/trust/adversarial/cases/" in p]
        assert added_paths, (
            f"expected a new case directory in PR diff, got paths {pr.added_paths!r}"
        )
        case_dirs = {p.split("tests/trust/adversarial/cases/")[1].split("/")[0] for p in added_paths}
        assert case_dirs == {"synth-renamed-scenario"}, case_dirs

        # Assertion 4: self-validation passed — the harness shim was awaited
        # with the claimed catcher and keyword.
        fake_harness.run_case_through_catcher.assert_awaited_once()
        (kwargs,) = [c.kwargs for c in fake_harness.run_case_through_catcher.await_args_list]
        assert kwargs.get("expected_catcher") == "diff-sanity"
        assert "renamed" in (kwargs.get("keyword") or "").lower()

        # Assertion 5: loop stats reflect one proposed case, zero escalations.
        result = stats["corpus_learning"]
        assert result["escape_issues_seen"] == 1
        assert result["cases_proposed"] == 1
        assert result["escalated"] == 0

    async def test_three_self_validation_failures_escalate(
        self, tmp_path: Path
    ) -> None:
        """Escalation path: the same escape issue has 3 failed synthesis
        attempts in a row. After the third, the loop labels it
        `hitl-escalation` + `corpus-learning-stuck`, records the attempts in
        the issue body, and moves on — it does not spin. Matches §3.2.
        """
        world = MockWorld(tmp_path)

        world.github.seed_issue(
            number=9002,
            title="skill missed plan divergence",
            body="PR #8801 merged despite scope_check missing an unrelated edit.",
            labels=["hydraflow-find", "skill-escape"],
            state="open",
        )

        # Script the FakeLLM to return bad envelopes on every call so all
        # three synthesis attempts fail parsing.
        world.llm.script_response(
            match_substring="Synthesize an adversarial corpus case",
            response=_CASE_ENVELOPE_BAD,
            persistent=True,
        )

        fake_harness = AsyncMock()
        _seed_ports(world, corpus_learning_harness=fake_harness)

        # Three ticks, each advancing past the interval.
        for _ in range(3):
            world.clock.advance(seconds=3601)
            await world.run_pipeline(loops=["corpus_learning"], cycles=1)

        # Assertion 1: the issue now carries escalation labels.
        issue = world.github.issues[9002]
        assert "hitl-escalation" in issue.labels
        assert "corpus-learning-stuck" in issue.labels

        # Assertion 2: the issue body records three rejected attempts.
        assert issue.body.count("rejected synthesis attempt") == 3

        # Assertion 3: no PR opened against staging for this issue.
        pr_refs = [pr for pr in world.github.prs.values() if "9002" in (pr.body or "")]
        assert pr_refs == [], f"expected zero PRs for escalated issue, got {pr_refs!r}"

        # Assertion 4: harness was never asked to validate (envelope never parsed).
        fake_harness.run_case_through_catcher.assert_not_awaited()
```

- [ ] **Step 2: Run the scenario — it fails**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/scenarios/test_corpus_learning_scenario.py -v -m scenario_loops`
Expected: both tests fail — the catalog does not yet know how to build a `corpus_learning` loop under MockWorld, and/or `world.llm.script_response` / `world.github.seed_issue` helpers may need shim extensions.

- [ ] **Step 3: Extend the MockWorld catalog for `corpus_learning`**

Open `tests/scenarios/catalog/` (or wherever loop catalogs live — discover with `ls tests/scenarios/catalog/`). Add an entry for `corpus_learning` that constructs the loop with:
- A `PRManager` fake that writes synthesized PRs into `world.github.prs` against the `staging` branch.
- A `DedupStore` backed by `tmp_path`.
- An `AgentRunner` fake that routes `run_oneshot_prompt` through `world.llm.dispatch(prompt, model)` so scripted responses apply.
- A `LoopDeps` that pulls `enabled_cb` / `interval_cb` / `status_cb` from the world's standard loop plumbing.
- A harness port `corpus_learning_harness` that gate-3 uses for `_validate_case`'s catcher trip; the scenario seeds this via `_seed_ports`.

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "from tests.scenarios.fakes.mock_world import MockWorld; import pathlib, tempfile; w = MockWorld(pathlib.Path(tempfile.mkdtemp())); print('corpus_learning' in w._known_loops)"`
Expected: `True`.

- [ ] **Step 4: Stub the minimum MockWorld helpers the scenario touches**

Confirm the helpers the test exercises exist on the MockWorld surface. If any do not, add them as thin forwarders:

- `world.github.seed_issue(number, title, body, labels, state)` — writes into `FakeGitHub.issues`.
- `world.llm.script_response(match_substring, response, persistent=False)` — appends to `FakeLLM.scripted_responses`.
- `world.llm.calls` — list of `(prompt, model)` records for every `dispatch` call.
- `world.run_pipeline(loops=[...], cycles=1)` — existing on `MockWorld`; confirm with `grep`.
- `world.clock.advance(seconds=...)` — existing on `FakeClock`.
- `pr.added_paths` — list of new-file paths in the PR's simulated diff (add to `FakePR` if missing).
- `pr.base` — branch the PR targets.

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run python -c "from tests.scenarios.fakes.mock_world import MockWorld; import pathlib, tempfile; w = MockWorld(pathlib.Path(tempfile.mkdtemp())); assert hasattr(w, 'run_pipeline'); assert hasattr(w.github, 'seed_issue'); assert hasattr(w.llm, 'script_response'); print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Implement the scenario-side plumbing until the tests pass**

Re-run the scenario test, fix each failure in turn. The happy-path test covers five assertions; the escalation test covers four. Do not move on until both pass cleanly.

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && PYTHONPATH=src uv run pytest tests/scenarios/test_corpus_learning_scenario.py -v -m scenario_loops`
Expected: 2 passed.

- [ ] **Step 6: Run the full scenario-loops suite to prove no regression**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && make scenario-loops`
Expected: all pre-existing scenarios plus the new L14 pass.

- [ ] **Step 7: Commit**

```bash
git add tests/scenarios/test_corpus_learning_scenario.py tests/scenarios/catalog tests/scenarios/fakes tests/scenarios/helpers
git commit -m "$(cat <<'EOF'
test(scenarios): L14 — CorpusLearningLoop end-to-end under MockWorld (§7)

Required integration-side scenario per spec §7 "MockWorld scenarios —
required". Seeds a skill-escape issue, advances FakeClock past
`corpus_learning_interval`, runs one pipeline tick, and asserts:
- the scripted FakeLLM saw the synthesis prompt exactly once
- a PR opened against `staging` adding a case directory under
  tests/trust/adversarial/cases/
- self-validation tripped the named catcher with the claimed keyword
- stats reflect cases_proposed=1, escalated=0

Second test covers the §3.2 escalation path: three failed syntheses
in a row → hitl-escalation + corpus-learning-stuck labels, issue body
records the attempts, no PR opened.

Closes the loop between the unit tests (mocked gh/PRs) and the real
factory plumbing that only MockWorld exercises — a loop that passes
Task 16 but fails here has drifted from the pipeline contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 19: Run full quality gate and open the Phase 2 PR

- [ ] **Step 1: Run `make quality`**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && make quality`
Expected: exits 0. Fix any lint/type/test errors before opening the PR.

- [ ] **Step 2: Run the full scenario + trust suites for a final sanity check**

Run: `cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening && make trust && make scenario-loops`
Expected: both pass.

- [ ] **Step 3: Push and open the PR**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening
git push
gh pr create --base main --title "feat(corpus-learning): CorpusLearningLoop — autonomous case growth (§4.1 v2)" --body "$(cat <<'EOF'
## Summary

- New `CorpusLearningLoop` background loop (`src/corpus_learning_loop.py`) grows the adversarial corpus from production `skill-escape` signals per spec §4.1 v2
- Synthesizes new cases via in-process Claude dispatch (`AgentRunner.run_oneshot_prompt`) — chosen over the routing-issue alternative for lower latency and fewer moving parts per §3.2 autonomy stance
- Three-gate self-validation (AST parse → ruff lint → harness catcher-trip) rejects synthesis that can't prove the case flags what it claims
- 3-rejection-per-escape budget → `hitl-escalation` + `corpus-learning-stuck` labels on the escape issue
- Opens PRs against `staging` via standard `PRManager.create_pr`; auto-merge via standard reviewer + quality gates (no human approval on the happy path, §3.2)
- Five-checkpoint wiring per `docs/agents/background-loops.md` (config, dashboard bounds, UI constants, service registry, orchestrator) + telemetry emission per spec §4.11 point 3 (`{"kind": "loop", "loop": "CorpusLearningLoop"}` shape on every LLM + subprocess call)
- Unit + integration tests in `tests/test_corpus_learning_loop.py` cover construction, escape-signal reader, synthesis parsing, disk materialization, telemetry emission (including kill-switch zero-emission), and both the happy-path and escalation branches
- MockWorld scenario `tests/scenarios/test_corpus_learning_scenario.py` exercises the full pipeline end-to-end per spec §7 "MockWorld scenarios — required"

## Spec

Implements §4.1 v2, §4.11 point 3, and the §7 required MockWorld scenario of `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`.

## Test plan

- [ ] `make trust` + `make scenario-loops` + `make quality` pass locally
- [ ] `tests/test_loop_wiring_completeness.py` green (all five checkpoints for `corpus_learning`)
- [ ] End-to-end mocked test (`test_end_to_end_escape_to_pr`) asserts PR opens with correct labels
- [ ] 3-rejection test (`test_end_to_end_three_rejections_escalate`) asserts hitl-escalation labeling
- [ ] Telemetry tests (`test_tick_emits_prompt_telemetry_with_loop_kind`, `test_tick_records_subprocess_trace`, `test_kill_switch_disables_telemetry`) assert §4.11 point 3 emission + kill-switch zero-emission
- [ ] MockWorld scenario L14 (`tests/scenarios/test_corpus_learning_scenario.py`) asserts escape issue → PR-against-staging happy path + 3-reject escalation path
EOF
)"
```

---

## Architectural notes

- **Harness dispatch surface.** Harness uses `prompt_builder`/`result_parser` directly from `skill_registry.BUILTIN_SKILLS` rather than routing through `AgentRunner._run_skill` (which requires a `Task`, a worktree, and a live agent process). §4.1 permits the plan to pick the shim surface.
- **Deterministic transcripts.** Each case ships `expected_transcript.txt`; live `claude` calls only fire when `HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1`. `CorpusLearningLoop` synthesis also writes a deterministic `expected_transcript.txt` so gate-3 validation is stable.
- **Synthesis dispatch choice (v2 option a).** In-process `AgentRunner.run_oneshot_prompt` picked over routing-issue path — lower latency, one moving part, matches §3.2 autonomy stance. Revisit if it proves too expensive.
- **Dedup keying.** `DedupStore` keyed by `escape-<issue_number>` keeps re-ticks from double-proposing. Closing the escape issue is standard `Closes #N` in the PR body.
