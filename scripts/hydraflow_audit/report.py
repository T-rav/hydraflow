"""Write the audit report as JSON and print a terminal summary."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .models import Finding, Status

_STATUS_GLYPH = {
    Status.PASS: "✓",
    Status.WARN: "!",
    Status.FAIL: "✗",
    Status.NA: "-",
    Status.INERT: "∅",
    Status.NOT_IMPLEMENTED: "?",
}


def build_payload(findings: list[Finding]) -> dict:
    return {
        "version": 1,
        "summary": _summarise(findings),
        "findings": [f.to_dict() for f in findings],
    }


def write_json(findings: list[Finding], out_path: Path) -> dict:
    payload = build_payload(findings)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def format_terminal(findings: list[Finding]) -> str:
    lines: list[str] = ["HydraFlow Conformance Audit (ADR-0044)", "=" * 40, ""]
    by_principle: dict[str, list[Finding]] = {}
    for f in findings:
        by_principle.setdefault(f.principle, []).append(f)

    for principle in sorted(by_principle, key=_principle_sort_key):
        bucket = by_principle[principle]
        counts = Counter(f.status for f in bucket)
        headline = (
            f"{principle}  "
            f"PASS {counts[Status.PASS]} / "
            f"WARN {counts[Status.WARN]} / "
            f"FAIL {counts[Status.FAIL]} / "
            f"NA {counts[Status.NA]} / "
            f"INERT {counts[Status.INERT]} / "
            f"?? {counts[Status.NOT_IMPLEMENTED]}"
        )
        lines.append(headline)
        for f in bucket:
            if f.status is Status.PASS:
                continue
            glyph = _STATUS_GLYPH[f.status]
            lines.append(f"  {glyph} {f.check_id}  {f.what}")
            if f.message:
                lines.append(f"      {f.message}")
            lines.append(f"      source: {f.source}  —  fix: {f.remediation}")
        lines.append("")

    summary = _summarise(findings)
    lines.append(
        f"Total: PASS {summary['pass']}  WARN {summary['warn']}  FAIL {summary['fail']}  "
        f"NA {summary['na']}  INERT {summary['inert']}  "
        f"NOT_IMPLEMENTED {summary['not_implemented']}"
    )
    lines.extend(_inert_banner(findings))
    return "\n".join(lines)


def _inert_banner(findings: list[Finding]) -> list[str]:
    """Name every inert check under the totals, where it cannot be scrolled past.

    A count in a row of counts is easy to read as noise. The failure this
    guards against is precisely someone glancing at a green-looking audit and
    moving on, so an inert check gets its own block, by id, with the reason it
    could not measure anything.
    """
    inert = [f for f in findings if f.status is Status.INERT]
    if not inert:
        return []
    lines = [
        "",
        "!" * 40,
        f"{len(inert)} INERT check(s) — the audit advertises these but did not",
        "perform them. An absent subject is not a passing subject.",
        "!" * 40,
    ]
    lines.extend(f"  \u2205 {f.check_id}  {f.message}" for f in inert)
    return lines


def _summarise(findings: list[Finding]) -> dict[str, int]:
    counts = Counter(f.status for f in findings)
    return {
        "pass": counts[Status.PASS],
        "warn": counts[Status.WARN],
        "fail": counts[Status.FAIL],
        "na": counts[Status.NA],
        "inert": counts[Status.INERT],
        "not_implemented": counts[Status.NOT_IMPLEMENTED],
        "total": len(findings),
    }


def _principle_sort_key(principle: str) -> tuple[int, str]:
    try:
        return (int(principle.lstrip("P")), principle)
    except ValueError:
        return (9999, principle)
