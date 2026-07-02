# tests/test_adr_conformance_coverage.py
"""Coverage ratchet (ADR-0100): every Accepted ADR declares Enforcement,
and every `enforced` check resolves and is side-effect-free. Mirrors
tests/test_loop_fitness_completeness.py. _GRANDFATHERED SHRINKS only.
"""

from __future__ import annotations

import re
from pathlib import Path

from adr_conformance import classify_enforcement, is_mutating, resolve_check
from adr_index import scan_adr_directory

REPO = Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"

# Any file whose FIRST line is an ADR heading, regardless of the separator
# used after the number (colon, em-dash, en-dash, hyphen, bare whitespace).
# Mirrors adr_index._TITLE_RE's number-capture but is intentionally a
# simpler/independent check: this test exists to catch _TITLE_RE silently
# regressing to a narrower format again (the ADR-0100 bug this ratchet
# closes), so it must not share the production regex.
_ADR_HEADING_RE = re.compile(r"^#\s*ADR-(\d{4})\b")

# Extracts the raw status value from either of the two forms ADRs actually
# use: bold-inline (`**Status:** Accepted`) or H2 heading
# (`## Status\n\nAccepted`). Intentionally independent of
# adr_index._STATUS_RE / _STATUS_H2_RE — this test exists to catch those
# regexes silently regressing to a narrower format again (the same class of
# bug as _ADR_HEADING_RE above, this time for status instead of title: the
# H2 form was invisible to _STATUS_RE for 13 ADRs, including ADR-0053, until
# this fix), so it must not share the production regex.
_STATUS_SECTION_RE = re.compile(
    r"\*\*Status:\*\*\s*(.+?)\s*$|^##\s+Status\s*\n+([^\n]+)", re.MULTILINE
)
# Words that MUST normalize to a known bucket (Accepted/Proposed/Superseded/
# Deprecated) via adr_index._normalize_status. A status value containing one
# of these words but still coming back "Unknown" from scan_adr_directory is
# unambiguously a parser regression, not a legitimately-unmodeled status
# word (e.g. "Rejected", which _normalize_status intentionally buckets as
# "Unknown" since it isn't one of the four load-bearing statuses).
_RECOGNIZED_STATUS_WORDS_RE = re.compile(
    r"accepted|proposed|draft|superseded|deprecated", re.IGNORECASE
)

# Fixed snapshot of every Accepted ADR number that was NOT annotated, as of
# the status-completeness fix (this task): adr_index._STATUS_RE was broadened
# to also match the `## Status` H2 heading form (not just bold-inline
# `**Status:**`), so 13 previously-invisible ADRs — including 0053 — now
# parse with a real status and enter this ratchet for the first time.
# Re-derived from (Task 13's baseline of 46) + (13 newly-visible H2-status
# Accepted ADRs) - (0053, which moves from invisible straight to annotated).
# NEVER edit this literal — it is the baseline the subset guard below checks
# against. Backfill tasks shrink the *live* grandfathered set by adding
# numbers to `_ANNOTATED`, not by editing this frozenset.
_GRANDFATHER_BASELINE: frozenset[int] = frozenset(
    {
        1,
        4,
        5,
        7,
        8,
        9,
        10,
        11,
        12,
        14,
        15,
        16,
        17,
        18,
        19,
        21,
        22,
        23,
        24,
        25,
        27,
        28,
        29,
        30,
        31,
        32,
        34,
        35,
        36,
        37,
        41,
        43,
        45,
        47,
        50,
        51,
        52,
        54,
        55,
        57,
        58,
        60,
        61,
        62,
        64,
        65,
        71,
        83,
        85,
        88,
        89,
        90,
        91,
        92,
        94,
        95,
        96,
        # 97/98 merged concurrently from convergence Phase 2c/2d (0097 ledger
        # migration, 0098 oscillation caretaker) after this baseline was first
        # snapshotted; they predate the conformance convention, so they are
        # grandfathered here (backlog to annotate later), not force-annotated.
        97,
        98,
    }
)

# ADRs annotated with **Enforcement:** by backfill tasks, removed from the
# live grandfathered set. Task 13 annotates 0002/0003/0042/0056/0093; Tasks
# 14/15 added 49 (kill-switch convention) and 53 (ubiquitous language) — both
# in _ANNOTATED and both NOT in _GRANDFATHER_BASELINE (49 was already excluded
# pre-fix; 53 skips grandfathering entirely via the status-completeness fix).
#
# The grandfather-backfill campaign (2026-07-01) then annotated ALL 59
# remaining baseline ADRs with a real **Enforcement:** declaration and added
# their numbers here, draining the live grandfathered set to ∅. There is no
# standing conformance exemption left: every Accepted ADR now declares its
# enforcement. New Accepted ADRs are held to the same bar by
# test_every_accepted_adr_declares_enforcement (see docs/adr/README.md
# "Adding a new ADR"). _GRANDFATHER_BASELINE stays a fixed size-59 snapshot;
# the set only ever shrinks by growing _ANNOTATED, never by editing it.
_ANNOTATED: frozenset[int] = frozenset(
    {
        1,
        2,
        3,
        4,
        5,
        7,
        8,
        9,
        10,
        11,
        12,
        14,
        15,
        16,
        17,
        18,
        19,
        21,
        22,
        23,
        24,
        25,
        27,
        28,
        29,
        30,
        31,
        32,
        34,
        35,
        36,
        37,
        41,
        42,
        43,
        45,
        47,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        60,
        61,
        62,
        64,
        65,
        71,
        83,
        85,
        88,
        89,
        90,
        91,
        92,
        93,
        94,
        95,
        96,
        97,
        98,
    }
)

# Live grandfathered set: baseline minus everything annotated so far. A true
# subset of the baseline, so it can only shrink — never grow, and never swap
# one exemption for another same-size one.
_GRANDFATHERED: frozenset[int] = _GRANDFATHER_BASELINE - _ANNOTATED


def _accepted():
    return [a for a in scan_adr_directory(ADR_DIR) if a.status == "Accepted"]


def test_every_adr_file_parses():
    """No silent skips: every docs/adr/*.md file with an ADR heading must
    come back from scan_adr_directory. This is the regression test for the
    bug this ratchet exists to close — _TITLE_RE required a colon after the
    ADR number, so em-dash-titled ADRs (e.g. ADR-0093) were invisible to
    scan_adr_directory and therefore invisible to every check in this file.
    A parser that silently drops files defeats the whole coverage premise.
    """
    on_disk: set[int] = set()
    for p in ADR_DIR.glob("*.md"):
        text = p.read_text()
        first_line = text.splitlines()[0] if text else ""
        m = _ADR_HEADING_RE.match(first_line)
        if m:
            on_disk.add(int(m.group(1)))

    parsed = {a.number for a in scan_adr_directory(ADR_DIR)}

    missing = on_disk - parsed
    assert not missing, (
        f"scan_adr_directory silently skipped ADR file(s) for number(s) "
        f"{sorted(missing)} — every file with an '# ADR-NNNN' heading must "
        f"parse. Check _TITLE_RE against the file's actual title separator."
    )


def test_every_adr_with_a_status_section_parses_known_status():
    """No silent status-parse failures: every ADR file whose status section
    (`**Status:**` bold-inline OR `## Status` H2 heading) contains one of
    the four load-bearing status words (Accepted/Proposed/Superseded/
    Deprecated) must parse to that bucket, not "Unknown".

    This is the regression test for the sibling bug to
    ``test_every_adr_file_parses``: adr_index._STATUS_RE only matched the
    bold-inline form, so 13 ADRs using the `## Status` H2 heading (including
    ADR-0053) parsed as ``status="Unknown"`` and were silently excluded from
    ``_accepted()`` — and therefore from this entire ratchet. ADR-0053's
    ``**Enforcement:** enforced`` annotation was a no-op as a result.

    Scoped to status values containing a recognized word so it doesn't flag
    ADRs with a genuinely different, unmodeled status word (e.g. ADR-0039/
    0040's ``**Status:** Rejected`` — "Rejected" isn't one of the four
    normalized buckets by design, and correctly parses to "Unknown"; that is
    not a parser bug).
    """
    on_disk: set[int] = set()
    for p in ADR_DIR.glob("*.md"):
        text = p.read_text()
        first_line = text.splitlines()[0] if text else ""
        heading_match = _ADR_HEADING_RE.match(first_line)
        if not heading_match:
            continue
        status_match = _STATUS_SECTION_RE.search(text)
        if not status_match:
            continue
        raw_value = status_match.group(1) or status_match.group(2) or ""
        if _RECOGNIZED_STATUS_WORDS_RE.search(raw_value):
            on_disk.add(int(heading_match.group(1)))

    by_number = {a.number: a for a in scan_adr_directory(ADR_DIR)}
    still_unknown = sorted(n for n in on_disk if by_number[n].status == "Unknown")
    assert not still_unknown, (
        f"ADR(s) {still_unknown} have a status section containing a "
        "recognized status word (Accepted/Proposed/Superseded/Deprecated) "
        "but parsed to status='Unknown' — check adr_index._STATUS_RE / "
        "_STATUS_H2_RE against the file's actual status format. A silent "
        "status-parse failure hides the ADR from every check in this "
        "ratchet (see ADR-0053's grandfathering note)."
    )


def test_every_accepted_adr_declares_enforcement():
    offenders = [
        a.number
        for a in _accepted()
        if a.number not in _GRANDFATHERED
        and classify_enforcement(a.enforcement) is None
    ]
    assert not offenders, f"ADRs missing/invalid **Enforcement:** {offenders}"


def test_enforced_adrs_name_resolvable_nonmutating_checks():
    problems: list[str] = []
    for a in _accepted():
        if a.number in _GRANDFATHERED or a.enforcement != "enforced":
            continue
        if not a.enforced_by:
            problems.append(f"ADR-{a.number:04d}: enforced but no Enforced-by")
            continue
        for chk in a.enforced_by:
            if chk.kind == "prose":
                problems.append(
                    f"ADR-{a.number:04d}: prose check under enforced ({chk.raw!r})"
                )
            elif is_mutating(chk):
                problems.append(
                    f"ADR-{a.number:04d}: mutating target {chk.target!r} not allowed"
                )
            elif not resolve_check(chk, REPO):
                problems.append(f"ADR-{a.number:04d}: unresolved check {chk.raw!r}")
    assert not problems, "\n".join(problems)


def test_manual_adrs_have_a_process_pointer():
    offenders = [
        a.number
        for a in _accepted()
        if a.number not in _GRANDFATHERED
        and a.enforcement == "manual"
        and not a.enforced_by
    ]
    assert not offenders, f"manual ADRs missing an Enforced-by pointer: {offenders}"


def test_grandfather_only_shrinks():
    assert _GRANDFATHERED <= _GRANDFATHER_BASELINE, (
        "_GRANDFATHERED is not a subset of _GRANDFATHER_BASELINE — exempting an "
        "ADR from the conformance ratchet is meta-level rubber-stamping. "
        "Annotate the ADR instead of swapping one exemption for another."
    )
    assert len(_GRANDFATHER_BASELINE) == 59, (
        "_GRANDFATHER_BASELINE changed size — it is a fixed snapshot, most "
        "recently re-derived by the status-completeness fix (adr_index._STATUS_RE "
        "widened to also match the '## Status' H2 heading form, so 13 "
        "previously-invisible ADRs now enter this ratchet) and must never be "
        "edited again. Shrink the live grandfathered set by adding annotated "
        "ADR numbers to _ANNOTATED instead."
    )
