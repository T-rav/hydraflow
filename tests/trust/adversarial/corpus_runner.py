"""Adversarial corpus runner — shared eval logic for the pytest harness and the
``FORMAT=json`` producer consumed by ``SkillPromptEvalLoop._run_corpus``.

A *case* lives at ``tests/trust/adversarial/cases/<name>/``:

  - ``before/`` / ``after/``     minimal pre/post-diff repo subset
  - ``expected_catcher.txt``     a registered skill name, or ``"none"``
  - ``README.md``                describes the bug + a ``Keyword:`` line
  - ``expected_transcript.txt``  (optional) canned LLM transcript fixture
  - ``plan.md`` / ``provenance.txt``  (optional)

Document-judging skills read their real inputs from conventional paths inside
``before/`` / ``after/`` rather than from the synthesized diff — see
``_SKILL_INPUT_FILES`` (``before/issue.md`` + ``after/brief.md`` for
``discover-completeness``; ``before/discover_brief.md`` + ``after/proposal.md``
for ``shape-coherence``).

``evaluate_case`` synthesizes a unified diff from ``before/`` vs ``after/``,
feeds it to every skill's ``prompt_builder``, parses the transcript with each
skill's ``result_parser``, and decides a per-case ``status``:

  - ``PASS``  — expected behaviour holds (the expected catcher flags the case
                with its keyword; or, for ``none`` cases, no skill flags it).
  - ``FAIL``  — a regression: the catcher no longer flags it (or a ``none``
                case is now flagged).
  - ``SKIPPED`` — no transcript fixture and live mode off (non-strict only).

The pytest harness asserts on this; the loop diffs ``PASS -> FAIL`` per case to
detect skill-prompt drift. Run ``python corpus_runner.py --json`` to emit the
loop-facing result list (``[{case_id, skill, status, provenance,
expected_catcher, summary}, ...]``) on stdout. ``summary`` carries the failing
run's transcript summary — the refiner reads it as the failure transcript, so
the slim projection must include it (empty string when a branch produced none).

Live mode (``HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1``, the weekly backstop): up to
``HYDRAFLOW_TRUST_ADVERSARIAL_LIVE_BUDGET`` catcher-skill cases are evaluated
via the per-skill path (:func:`evaluate_case_for_skill` with ``force_live``),
round-robin across skills, so every skill's OWN prompt gets exercised against
the real agent CLI — not just ``BUILTIN_SKILLS[0]``'s (#10014). Cases beyond
the budget, ``"none"`` sentinels, and every non-live run replay their
``expected_transcript.txt`` fixtures exactly as before.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE / "cases"
REPO_ROOT = HERE.parent.parent.parent
SRC = REPO_ROOT / "src"

# Mirror the conftest sys.path setup: bare imports (skill_registry) resolve via
# src/, while modules that self-reference as ``src.X`` (e.g. models.py) need the
# repo root on the path too.
for _path in (REPO_ROOT, SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from skill_registry import BUILTIN_SKILLS  # noqa: E402

_SKILLS_BY_NAME = {s.name: s for s in BUILTIN_SKILLS}
_VALID_CATCHERS: frozenset[str] = frozenset({*_SKILLS_BY_NAME.keys(), "none"})


class MissingTranscriptError(RuntimeError):
    """Raised in strict mode when a case has no transcript fixture and live is off."""


HOLDOUT_MARKER = "HOLDOUT"

# Default cap on how many catcher-skill cases a live run evaluates via the
# per-skill live path (one real agent-CLI call each). The weekly backstop
# forwards the operator knob (`skill_prompt_eval_live_case_budget`) via
# HYDRAFLOW_TRUST_ADVERSARIAL_LIVE_BUDGET; this constant only covers manual
# runs where the env var is absent. Keep the two defaults aligned.
DEFAULT_LIVE_BUDGET = 12

# Per-skill prompt-input fixtures (#10014). The document-judging skills
# (`discover-completeness`, `shape-coherence`) take their real inputs as
# builder kwargs (`issue_body`/`brief`, `discover_brief`/`proposal`) — the
# generic diff/plan call in `evaluate_case_for_skill` leaves those empty (the
# builders `**_kwargs`-swallow `diff`/`plan_text` and return "" without their
# document), which fed `claude -p ""` on the live path. The case-dir
# convention already stores the documents as before/after content; thread
# them through explicitly. Keyed per skill so builders without `**_kwargs`
# (e.g. `plan-compliance`) never receive unexpected keywords.
_SKILL_INPUT_FILES: dict[str, dict[str, str]] = {
    "discover-completeness": {
        "issue_body": "before/issue.md",
        "brief": "after/brief.md",
    },
    "shape-coherence": {
        "discover_brief": "before/discover_brief.md",
        "proposal": "after/proposal.md",
    },
}


def load_skill_input_texts(case_dir: Path, skill_name: str) -> dict[str, str]:
    """Builder kwargs harvested from *case_dir*'s conventional input files.

    Returns only the entries whose file exists, and only for *skill_name*'s
    registered mapping — an empty dict for diff-judging skills.
    """
    out: dict[str, str] = {}
    for kwarg, rel in _SKILL_INPUT_FILES.get(skill_name, {}).items():
        path = case_dir / rel
        if path.is_file():
            out[kwarg] = path.read_text(encoding="utf-8")
    return out


def is_holdout(case_dir: Path) -> bool:
    """True when *case_dir* is a held-out honeypot (never shown to the refiner)."""
    return (case_dir / HOLDOUT_MARKER).is_file()


def discover_cases(
    cases_dir: Path = CASES_DIR, *, include_holdout: bool = True
) -> list[Path]:
    if not cases_dir.is_dir():
        return []
    return sorted(
        p
        for p in cases_dir.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        and (include_holdout or not is_holdout(p))
    )


def _read_case_files(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            try:
                out[rel] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                out[rel] = ""
    return out


def synthesize_diff(before_dir: Path, after_dir: Path) -> str:
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


def load_transcript(
    case_dir: Path, prompt: str, *, live: bool, force_live: bool = False
) -> str | None:
    """Return the canned transcript for *case_dir*, invoke live claude, or None.

    Returns ``None`` when no ``expected_transcript.txt`` exists and *live* is
    off — callers decide whether that is a skip or an error. *force_live*
    (only meaningful with ``live=True``) skips the fixture short-circuit so a
    budgeted backstop case genuinely exercises the current prompt against the
    real agent CLI instead of replaying its canned transcript.
    """
    fixture = case_dir / "expected_transcript.txt"
    if fixture.exists() and not (live and force_live):
        return fixture.read_text(encoding="utf-8")
    if not live:
        return None
    result = subprocess.run(  # noqa: S603
        ["claude", "-p", prompt, "--output-format", "text"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    return result.stdout


def read_keyword(readme_path: Path) -> str:
    """Extract the required ``Keyword:`` from a case README (case-insensitive)."""
    text = readme_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().lower().startswith("keyword:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"README.md {readme_path} missing 'Keyword:' line")


def read_expected_catcher(case_dir: Path) -> str:
    catcher = (case_dir / "expected_catcher.txt").read_text(encoding="utf-8").strip()
    if catcher not in _VALID_CATCHERS:
        raise AssertionError(
            f"{case_dir.name}/expected_catcher.txt = {catcher!r}; must be one of "
            f"{sorted(_VALID_CATCHERS)} (from live skill_registry.BUILTIN_SKILLS)"
        )
    return catcher


def load_plan_text(case_dir: Path) -> str:
    plan = case_dir / "plan.md"
    return plan.read_text(encoding="utf-8") if plan.exists() else ""


def read_provenance(case_dir: Path) -> str:
    """Return the case provenance (``provenance.txt``), defaulting to hand-crafted."""
    prov = case_dir / "provenance.txt"
    if prov.exists():
        text = prov.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "hand-crafted"


def evaluate_case(
    case_dir: Path, *, live: bool = False, strict: bool = True
) -> dict[str, Any]:
    """Evaluate one case and return its loop-facing result dict.

    Keys: ``case_id, skill, expected_catcher, provenance, status`` plus
    ``summary`` and ``findings`` for the pytest assertions. ``status`` is one of
    ``PASS`` / ``FAIL`` / ``SKIPPED``.

    In *strict* mode a missing transcript raises :class:`MissingTranscriptError`
    (the pytest harness requires a fixture or live mode); otherwise the case is
    reported ``SKIPPED`` so the loop simply ignores it.
    """
    case_id = case_dir.name
    before_dir = case_dir / "before"
    after_dir = case_dir / "after"
    if not before_dir.is_dir() or not after_dir.is_dir():
        raise AssertionError(f"{case_id}: missing before/ or after/")

    diff = synthesize_diff(before_dir, after_dir)
    if not diff.strip():
        raise AssertionError(f"{case_id}: before/ and after/ produced empty diff")

    catcher = read_expected_catcher(case_dir)
    provenance = read_provenance(case_dir)
    plan_text = load_plan_text(case_dir)

    # One transcript per case, fed to every skill's parser (the prompt arg only
    # matters for the live-claude path).
    sample_prompt = ""
    if BUILTIN_SKILLS:
        sample_prompt = BUILTIN_SKILLS[0].prompt_builder(
            issue_number=0,
            issue_title=f"adversarial-corpus::{case_id}",
            diff=diff,
            plan_text=plan_text,
        )
    transcript = load_transcript(case_dir, sample_prompt, live=live)
    if transcript is None:
        if strict:
            raise MissingTranscriptError(
                f"No expected_transcript.txt for {case_id}; set "
                "HYDRAFLOW_TRUST_ADVERSARIAL_LIVE=1 to invoke the real claude CLI."
            )
        return {
            "case_id": case_id,
            "skill": catcher,
            "expected_catcher": catcher,
            "provenance": provenance,
            "status": "SKIPPED",
            "summary": "",
            "findings": [],
        }

    results: dict[str, tuple[bool, str, list[str]]] = {}
    for skill in BUILTIN_SKILLS:
        results[skill.name] = skill.result_parser(transcript)

    if catcher == "none":
        failing = [name for name, (passed, _, _) in results.items() if not passed]
        status = "PASS" if not failing else "FAIL"
        return {
            "case_id": case_id,
            "skill": "none",
            "expected_catcher": "none",
            "provenance": provenance,
            "status": status,
            "summary": "" if status == "PASS" else f"flagged by {failing}",
            "findings": failing,
        }

    passed, summary, findings = results[catcher]
    keyword = read_keyword(case_dir / "README.md")
    haystack = (summary + "\n" + "\n".join(findings)).lower()
    caught = (not passed) and (keyword.lower() in haystack)
    return {
        "case_id": case_id,
        "skill": catcher,
        "expected_catcher": catcher,
        "provenance": provenance,
        "status": "PASS" if caught else "FAIL",
        "summary": summary,
        "findings": findings,
    }


def evaluate_case_for_skill(
    case_dir: Path, skill_name: str, *, live: bool = False, force_live: bool = False
) -> dict[str, Any]:
    """Evaluate one case against ONE skill, building THAT skill's prompt.

    Unlike :func:`evaluate_case` (one transcript, all parsers), this is the
    per-skill path — refine-candidate validation and the budgeted live
    backstop: the target skill's own ``prompt_builder`` produces the live
    prompt (document-judging skills get their real inputs threaded via
    :func:`load_skill_input_texts`), and only its parser judges the
    transcript. Cases whose ``expected_catcher`` is neither *skill_name* nor
    ``"none"`` return ``SKIPPED``.

    *force_live* bypasses the fixture short-circuit (see
    :func:`load_transcript`). A case whose builder renders an empty prompt —
    its input documents are absent, the skills' "no input data" signal —
    falls back to fixture replay instead of invoking the CLI on "".
    """
    case_id = case_dir.name
    catcher = read_expected_catcher(case_dir)
    provenance = read_provenance(case_dir)
    if catcher not in (skill_name, "none"):
        return {
            "case_id": case_id,
            "skill": skill_name,
            "status": "SKIPPED",
            "expected_catcher": catcher,
            "provenance": provenance,
            "summary": "",
            "findings": [],
        }
    skill = next(s for s in BUILTIN_SKILLS if s.name == skill_name)
    diff = synthesize_diff(case_dir / "before", case_dir / "after")
    prompt = skill.prompt_builder(
        issue_number=0,
        issue_title=f"adversarial-corpus::{case_id}",
        diff=diff,
        plan_text=load_plan_text(case_dir),
        **load_skill_input_texts(case_dir, skill_name),
    )
    if not prompt.strip():
        force_live = False
    transcript = load_transcript(case_dir, prompt, live=live, force_live=force_live)
    if transcript is None:
        return {
            "case_id": case_id,
            "skill": skill_name,
            "status": "SKIPPED",
            "expected_catcher": catcher,
            "provenance": provenance,
            "summary": "",
            "findings": [],
        }
    passed, summary, findings = skill.result_parser(transcript)
    if catcher == "none":
        status = "PASS" if passed else "FAIL"
    else:
        keyword = read_keyword(case_dir / "README.md")
        haystack = (summary + "\n" + "\n".join(findings)).lower()
        status = "PASS" if (not passed and keyword.lower() in haystack) else "FAIL"
    return {
        "case_id": case_id,
        "skill": skill_name,
        "status": status,
        "expected_catcher": catcher,
        "provenance": provenance,
        "summary": summary,
        "findings": findings,
    }


def select_live_skill_cases(case_dirs: list[Path], budget: int) -> set[str]:
    """Case names to route through the per-skill LIVE path, at most *budget*.

    Round-robin across expected catchers (``"none"`` sentinels excluded) so a
    small budget still exercises every skill's OWN prompt at least once —
    a plain first-N slice of the sorted corpus would spend the whole budget
    on one alphabetically-early skill. Deterministic: skills and their cases
    are visited in sorted order.
    """
    if budget <= 0:
        return set()
    by_catcher: dict[str, list[Path]] = {}
    for case_dir in case_dirs:
        catcher = read_expected_catcher(case_dir)
        if catcher != "none":
            by_catcher.setdefault(catcher, []).append(case_dir)
    queues = [sorted(by_catcher[c], key=lambda p: p.name) for c in sorted(by_catcher)]
    selected: set[str] = set()
    rank = 0
    while len(selected) < budget and any(rank < len(q) for q in queues):
        for queue in queues:
            if rank < len(queue) and len(selected) < budget:
                selected.add(queue[rank].name)
        rank += 1
    return selected


def run_corpus(
    *,
    cases_dir: Path = CASES_DIR,
    live: bool = False,
    strict: bool = False,
    case_ids: frozenset[str] | None = None,
    live_budget: int = DEFAULT_LIVE_BUDGET,
) -> list[dict[str, Any]]:
    """Evaluate every discovered case and return the loop-facing result list.

    Holdouts are always included (the weekly backstop covers them) — pass
    *case_ids* to run a targeted subset by directory name.

    When *live* is on, up to *live_budget* catcher-skill cases (round-robin
    across skills — :func:`select_live_skill_cases`) run through the
    per-skill live path so each skill's OWN prompt is exercised against the
    real agent CLI (#10014); everything else replays fixtures via
    :func:`evaluate_case` exactly as in a non-live run.
    """
    case_dirs = [
        case_dir
        for case_dir in discover_cases(cases_dir)
        if case_ids is None or case_dir.name in case_ids
    ]
    live_cases = select_live_skill_cases(case_dirs, live_budget) if live else set()
    return [
        evaluate_case_for_skill(
            case_dir, read_expected_catcher(case_dir), live=True, force_live=True
        )
        if case_dir.name in live_cases
        else evaluate_case(case_dir, live=live, strict=strict)
        for case_dir in case_dirs
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adversarial corpus runner")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the loop-facing result list as JSON on stdout",
    )
    parser.add_argument(
        "--cases",
        default="",
        help="comma-separated case ids to run (default: all)",
    )
    parser.add_argument(
        "--live-skill",
        default="",
        help="evaluate only this skill's cases, building its own prompt/parser",
    )
    args = parser.parse_args(argv)
    live = os.environ.get("HYDRAFLOW_TRUST_ADVERSARIAL_LIVE") == "1"
    try:
        live_budget = int(os.environ.get("HYDRAFLOW_TRUST_ADVERSARIAL_LIVE_BUDGET", ""))
    except ValueError:
        live_budget = DEFAULT_LIVE_BUDGET
    case_ids = (
        frozenset(c.strip() for c in args.cases.split(",") if c.strip())
        if args.cases.strip()
        else None
    )
    if args.live_skill:
        results = [
            evaluate_case_for_skill(case_dir, args.live_skill, live=live)
            for case_dir in discover_cases(CASES_DIR)
            if case_ids is None or case_dir.name in case_ids
        ]
    else:
        results = run_corpus(
            live=live, strict=False, case_ids=case_ids, live_budget=live_budget
        )
    if args.json:
        # Only the loop-facing keys belong on stdout (the loop json.loads it).
        slim = [
            {
                "case_id": r["case_id"],
                "skill": r["skill"],
                "status": r["status"],
                "provenance": r["provenance"],
                "expected_catcher": r["expected_catcher"],
                # The loop reads this as the failure transcript fed to the
                # refiner (`case.get("summary","")`); omitting it left the
                # production refine context permanently blank. Both branches
                # now carry `summary`; `.get` stays as shape-safety.
                "summary": r.get("summary", ""),
            }
            for r in results
        ]
        print(json.dumps(slim))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
