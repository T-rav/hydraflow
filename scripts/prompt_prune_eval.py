#!/usr/bin/env python3
"""Prompt-prune eval harness (#10860).

Structural half of the "prune the long prompts with evals" loop. Renders every
registered prompt from the *working tree*, scores it against the ADR-0087 form
rubric, and compares both length and rubric verdicts to a frozen
``origin/staging`` baseline (``prompt_prune_baseline.json``). It reports the
token savings and FAILS if any prune introduced a new rubric failure — the cheap,
deterministic guardrail that catches structural damage.

It does NOT judge whether a prune dropped a load-bearing, project-specific
instruction a capable model still needs — that is the semantic half, done by a
Fable judge agent fed the old→new diff (see the PR / prune runbook). Both halves
gate a prune: structure here, behavior there.

Usage:
    python scripts/prompt_prune_eval.py            # whole corpus, table + totals
    python scripts/prompt_prune_eval.py NAME ...   # only these prompts (verbose)
Exit code 1 if any prompt regressed a rubric criterion vs the baseline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import audit_prompts as audit

_BASELINE = Path(__file__).with_name("prompt_prune_baseline.json")
_CHARS_PER_TOKEN = 4  # rough; only used for a human-readable savings estimate


def _current() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for target in audit.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        rendered = audit.render_target(target)
        scores = audit.score(rendered).scores
        out[target.name] = {
            "chars": len(rendered),
            "fails": sorted(c for c, v in scores.items() if v == "Fail"),
        }
    return out


def main(argv: list[str]) -> int:
    baseline = json.loads(_BASELINE.read_text())
    current = _current()
    only = set(argv) or None

    regressions: list[str] = []
    rows: list[tuple[str, int, int, int]] = []  # name, base_chars, cur_chars, delta
    for name, cur in sorted(current.items()):
        if only and name not in only:
            continue
        base = baseline.get(name)
        if base is None:
            print(f"  NEW prompt (no baseline): {name}")
            continue
        new_fails = set(cur["fails"]) - set(base["fails"])
        if new_fails:
            regressions.append(
                f"{name}: newly-failing rubric criteria {sorted(new_fails)}"
            )
        rows.append((name, base["chars"], cur["chars"], cur["chars"] - base["chars"]))

    rows.sort(key=lambda r: r[3])  # biggest savings first
    print(f"{'prompt':<42}{'base':>7}{'now':>7}{'Δchars':>8}{'Δtok~':>7}")
    total_base = total_cur = 0
    for name, b, c, d in rows:
        total_base += b
        total_cur += c
        if only or d != 0:
            print(f"{name:<42}{b:>7}{c:>7}{d:>+8}{d // _CHARS_PER_TOKEN:>+7}")
    saved = total_base - total_cur
    print(
        f"\nTOTAL {total_base} -> {total_cur} chars "
        f"({saved:+d} chars, ~{saved // _CHARS_PER_TOKEN:+d} tok across the corpus)"
    )

    if regressions:
        print("\nREGRESSIONS (rubric criteria that went Pass/Partial -> Fail):")
        for r in regressions:
            print(f"  ✗ {r}")
        return 1
    print("\nNo rubric regressions ✓ (structural guardrail green)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
