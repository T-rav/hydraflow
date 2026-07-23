"""Render the sampled-audit section of gauntlet-calibration.md (#10370).

The report is co-written with #10371 (judge-independence), which renders its own
section into the SAME ``docs/arch/generated/gauntlet-calibration.md``. To keep
the two additive (a merge is a clean concatenation, never a clobber), each loop
owns a MARKER-DELIMITED section and splices ONLY between its own markers,
preserving everything outside them. ``upsert_section`` is the pure splice;
``render_sampled_audit_section`` is the pure content render over a
``CalibrationSummary``.

Follows ``escape-ledger.md``'s generated-report convention: a runtime-written,
gitignored file each loop rewrites its own section of each tick — NOT an
``arch-regen`` artifact.
"""

from __future__ import annotations

from datetime import datetime

from audit.metrics import summarize
from audit.models import AuditSample, CalibrationSummary

# Section markers — the splice boundary. #10371 uses a DIFFERENT pair, so the
# two sections never overlap and either loop's write leaves the other intact.
BEGIN_MARKER = "<!-- BEGIN sampled-adversarial-reaudit (#10370) -->"
END_MARKER = "<!-- END sampled-adversarial-reaudit (#10370) -->"

_TITLE = "# Gauntlet calibration"
_TITLE_BLURB = (
    "> Auto-generated calibration surface for the gauntlet. Sections are "
    "co-written by independent instruments (#10370 sampled re-audit, #10371 "
    "judge independence); each owns a marker-delimited block. Do not hand-edit."
)


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_sampled_audit_section(summary: CalibrationSummary, *, now: datetime) -> str:
    """Render the sampled-audit section (between the markers, inclusive)."""
    ci = summary.disagreement
    lines: list[str] = [BEGIN_MARKER, ""]
    lines.append("## Sampled adversarial re-audit (#10370)")
    lines.append("")
    lines.append(
        "> The silent-escape estimator: a governed random sample of merged PRs "
        "re-reviewed by a fresh adversarial context. The disagreement rate is a "
        "statistical bound on the UNDETECTED escape rate. Read-only (ADR-0029 "
        "Pattern B): post-merge only, never gates, reverts, or opens fix PRs."
    )
    lines.append("")
    lines.append(f"_Generated at {now.isoformat()}_")
    lines.append("")

    lines.append("### Headline")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(f"| samples audited | {ci.n} |")
    lines.append(f"| **disagreement rate** | **{_fmt_pct(ci.rate)}** |")
    lines.append(
        f"| 95% confidence interval | {_fmt_pct(ci.lower)} – {_fmt_pct(ci.upper)} |"
    )
    lines.append(f"| auditor false-alarm rate | {_fmt_pct(summary.false_alarm_rate)} |")
    lines.append(f"| governed sample rate | {_fmt_pct(summary.governed_rate)} |")
    lines.append("")

    lines.append("### Per-gate-class calibration")
    lines.append("")
    lines.append("| blast-radius class | sampled | disagreements | upheld escapes |")
    lines.append("|---|---|---|---|")
    for row in summary.per_gate_class:
        lines.append(
            f"| {row.blast_radius_class} | {row.sampled} | "
            f"{row.disagreements} | {row.upheld} |"
        )
    if not summary.per_gate_class:
        lines.append("| (no samples yet) | 0 | 0 | 0 |")
    lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def upsert_section(
    existing: str, section: str, *, begin: str = BEGIN_MARKER, end: str = END_MARKER
) -> str:
    """Splice *section* into *existing* between *begin*/*end*, additively.

    Replaces the block between the markers when present; otherwise appends the
    section under the shared title, preserving any other loop's sections. Pure —
    the loop reads the file, upserts, writes back, so co-writers never clobber.
    """
    section = section.strip("\n")
    if begin in existing and end in existing:
        head, _, rest = existing.partition(begin)
        _, _, tail = rest.partition(end)
        return f"{head.rstrip()}\n\n{section}\n{tail.lstrip()}".rstrip() + "\n"

    base = existing.strip("\n")
    if not base:
        base = f"{_TITLE}\n\n{_TITLE_BLURB}"
    return f"{base}\n\n{section}\n"


def render_full_report(
    samples: list[AuditSample],
    *,
    now: datetime,
    governed_rate: float,
    existing: str = "",
) -> str:
    """Convenience: summarize samples and upsert the section into *existing*."""
    summary = summarize(samples, governed_rate=governed_rate)
    section = render_sampled_audit_section(summary, now=now)
    return upsert_section(existing, section)
