"""Adversarial corpus runner — shared eval logic for the pytest harness and the
``FORMAT=json`` producer consumed by ``SkillPromptEvalLoop._run_corpus``.

A *case* lives at ``tests/trust/adversarial/cases/<name>/``:

  - ``before/`` / ``after/``     minimal pre/post-diff repo subset
  - ``expected_catcher.txt``     a registered skill name, or ``"none"``
  - ``README.md``                describes the bug + a ``Keyword:`` line
  - ``expected_transcript.txt``  (optional) canned LLM transcript fixture
  - ``plan.md`` / ``provenance.txt``  (optional)

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
expected_catcher}, ...]``) on stdout.
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


def discover_cases(cases_dir: Path = CASES_DIR) -> list[Path]:
    if not cases_dir.is_dir():
        return []
    return sorted(
        p for p in cases_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
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


def load_transcript(case_dir: Path, prompt: str, *, live: bool) -> str | None:
    """Return the canned transcript for *case_dir*, invoke live claude, or None.

    Returns ``None`` when no ``expected_transcript.txt`` exists and *live* is
    off — callers decide whether that is a skip or an error.
    """
    fixture = case_dir / "expected_transcript.txt"
    if fixture.exists():
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


def run_corpus(
    *, cases_dir: Path = CASES_DIR, live: bool = False, strict: bool = False
) -> list[dict[str, Any]]:
    """Evaluate every discovered case and return the loop-facing result list."""
    return [
        evaluate_case(case_dir, live=live, strict=strict)
        for case_dir in discover_cases(cases_dir)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adversarial corpus runner")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the loop-facing result list as JSON on stdout",
    )
    args = parser.parse_args(argv)
    live = os.environ.get("HYDRAFLOW_TRUST_ADVERSARIAL_LIVE") == "1"
    results = run_corpus(live=live, strict=False)
    if args.json:
        # Only the loop-facing keys belong on stdout (the loop json.loads it).
        slim = [
            {
                "case_id": r["case_id"],
                "skill": r["skill"],
                "status": r["status"],
                "provenance": r["provenance"],
                "expected_catcher": r["expected_catcher"],
            }
            for r in results
        ]
        print(json.dumps(slim))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
