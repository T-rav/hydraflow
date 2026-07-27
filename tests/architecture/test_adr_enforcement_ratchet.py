"""Monotonic ADR-enforcement ratchet (epic #10623 Task 1 — the keystone).

Turns the honest-but-toothless enforcement-debt *report*
(`docs/arch/generated/adr-enforcement.md`) into a merge gate that rides
`make quality`. The rule this gate encodes is written up as a standard in
`docs/standards/adr_enforcement/README.md`:

    Every ``enforced`` Accepted ADR must classify REAL. A ``manual`` /
    ``decision-of-record`` kind is allowed only via an explicit, justified
    allow-list entry. The unenforced-decision debt is monotonically
    non-increasing — it may only shrink.

Source of truth is imported, never shelled out: ``classify_adr_enforcement``
(``src/adr_conformance.py``) labels each Accepted ADR REAL / WEAK / MISSING.
``WEAK`` + ``MISSING`` are the debt.

Two lanes drain the debt (see the standard for the full contract):

* **Baseline** — ``adr_enforcement_baseline.json`` grandfathers exactly the
  debt that existed when this ratchet landed. ``baseline_snapshot`` is a FROZEN
  literal (never add/remove ids). Pay a debt down by giving the ADR a REAL
  asserting check and adding its id to the JSON's ``resolved`` list; the live
  grandfathered set = ``baseline_snapshot - resolved - exempted``. Mirrors the
  ``_GRANDFATHERED = _BASELINE - _RESOLVED`` idiom in
  ``tests/test_adr_conformance_coverage.py`` and
  ``tests/architecture/test_duration_ratchet.py``.
* **Exemptions** — ``docs/standards/adr_enforcement/exemptions.md`` lists ADRs
  that legitimately cannot carry a resolving check (genuinely process-only
  decisions). Seeded EMPTY; each entry carries a one-line justification.

How to update the baseline legitimately:
  * A NEW Accepted ADR must ship REAL enforcement or a justified exemption — it
    is NEVER added to ``baseline_snapshot``.
  * A grandfathered ADR that gains a REAL check → move its id into ``resolved``.
  * A grandfathered ADR concluded to be process-only → add a justified entry to
    ``exemptions.md`` (it stays in the frozen snapshot but leaves the live set).

Consolidates and supersedes the earlier debt-only ratchet
(``test_adr_enforcement_debt.py``, issue #10411): same monotonic guarantee, now
backed by a committed baseline file + the exemptions allow-list + the written
standard, so debt is tracked in exactly one place.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from adr_conformance import EnforcementClass, classify_adr_enforcement
from adr_index import ADR, scan_adr_directory

REPO = Path(__file__).resolve().parents[2]
ADR_DIR = REPO / "docs" / "adr"
BASELINE_PATH = REPO / "tests" / "architecture" / "adr_enforcement_baseline.json"
EXEMPTIONS_PATH = REPO / "docs" / "standards" / "adr_enforcement" / "exemptions.md"

# Frozen tamper-guard: the exact debt set at ratchet landing (part of #10623).
# The JSON's ``baseline_snapshot`` must equal this literal. It NEVER changes —
# it is the fixed high-water mark. The live grandfathered set shrinks only by
# adding paid-off ids to the JSON's ``resolved`` list, never by editing either
# this frozenset or ``baseline_snapshot``.
#   WEAK  (manual prose):          9, 23, 25, 35, 42, 51, 65
#   MISSING (decision-of-record):  3, 27, 30, 91, 107
_FROZEN_SNAPSHOT: frozenset[int] = frozenset(
    {3, 9, 23, 25, 27, 30, 35, 42, 51, 65, 91, 107}
)

# Matches one exemption entry line in exemptions.md: `- ADR-NNNN: justification`.
# Prose that merely mentions an ADR does not match (must be a bullet + colon +
# non-empty justification), so the allow-list can live inside a prose doc.
_EXEMPTION_RE = re.compile(r"^-\s+ADR-(\d{4}):\s*(\S.*?)\s*$", re.MULTILINE)


def _accepted() -> list[ADR]:
    return [a for a in scan_adr_directory(ADR_DIR) if a.status == "Accepted"]


def _classification() -> dict[int, EnforcementClass]:
    return {a.number: classify_adr_enforcement(a, REPO) for a in _accepted()}


def _live_debt() -> set[int]:
    return {
        n
        for n, cls in _classification().items()
        if cls in (EnforcementClass.WEAK, EnforcementClass.MISSING)
    }


def _load_baseline() -> tuple[frozenset[int], frozenset[int]]:
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    snapshot = frozenset(int(n) for n in data["baseline_snapshot"])
    resolved = frozenset(int(n) for n in data.get("resolved", []))
    return snapshot, resolved


def _parse_exemptions() -> dict[int, str]:
    text = EXEMPTIONS_PATH.read_text(encoding="utf-8")
    return {int(m.group(1)): m.group(2).strip() for m in _EXEMPTION_RE.finditer(text)}


def _live_grandfathered() -> frozenset[int]:
    snapshot, resolved = _load_baseline()
    exempted = frozenset(_parse_exemptions())
    return snapshot - resolved - exempted


def test_baseline_snapshot_is_frozen_and_wellformed() -> None:
    """The committed baseline equals the frozen landing snapshot (12 ids) and
    ``resolved`` only ever names snapshot ADRs — the ratchet's fixed high-water
    mark cannot be tampered with."""
    snapshot, resolved = _load_baseline()

    assert snapshot == _FROZEN_SNAPSHOT, (
        "baseline_snapshot in adr_enforcement_baseline.json drifted from the "
        f"frozen landing set. Expected {sorted(_FROZEN_SNAPSHOT)}, got "
        f"{sorted(snapshot)}. baseline_snapshot is immutable — never add or "
        "remove ids. Shrink the live debt by adding a paid-off id to the "
        "`resolved` list, or exempt a process-only ADR in "
        "docs/standards/adr_enforcement/exemptions.md."
    )
    assert len(snapshot) == 12, (
        f"baseline_snapshot must stay the size-12 landing snapshot, got "
        f"{len(snapshot)}."
    )
    stray = sorted(resolved - snapshot)
    assert not stray, (
        f"`resolved` lists ADR(s) {stray} that were never in the debt baseline "
        "— you cannot pay down a debt that was never grandfathered. Only "
        f"snapshot ADRs {sorted(snapshot)} may be resolved."
    )


def test_no_new_or_ungrandfathered_debt() -> None:
    """Every non-exempt Accepted ADR that is WEAK/MISSING must be in the live
    grandfathered set — new decisions may not sneak in unenforced."""
    exempted = frozenset(_parse_exemptions())
    offenders = sorted(_live_debt() - exempted - _live_grandfathered())
    assert not offenders, (
        f"Accepted ADR(s) {offenders} are WEAK/MISSING but neither grandfathered "
        "nor exempt. Bind the decision to a REAL check: set "
        "`**Enforcement:** enforced` and cite a resolving, non-mutating, "
        "asserting `**Enforced by:** pytest:tests/...::Test...` (or "
        "`make:<guard>`). If the decision is genuinely process-only, add a "
        "justified entry to docs/standards/adr_enforcement/exemptions.md. Do "
        "NOT grow the baseline — see docs/standards/adr_enforcement/README.md."
    )


def test_debt_count_is_monotonically_non_increasing() -> None:
    """The non-exempt debt count may never exceed the baseline snapshot size —
    the ratchet only tightens."""
    snapshot, _ = _load_baseline()
    exempted = frozenset(_parse_exemptions())
    gated_debt = _live_debt() - exempted
    assert len(gated_debt) <= len(snapshot), (
        f"Unenforced-decision debt rose to {len(gated_debt)} non-exempt ADR(s), "
        f"above the baseline of {len(snapshot)}. Debt is monotonically "
        "non-increasing — enforce the new decision or justify an exemption "
        "instead of letting the tail grow."
    )


def test_grandfathered_debt_now_real_must_be_resolved() -> None:
    """A grandfathered ADR that has since gained a REAL enforcement must be
    moved into ``resolved`` so the ratchet tightens as debt is paid."""
    classes = _classification()
    now_real = sorted(
        n for n in _live_grandfathered() if classes.get(n) is EnforcementClass.REAL
    )
    assert not now_real, (
        f"Grandfathered ADR(s) {now_real} now classify REAL — move each id into "
        "the `resolved` list in tests/architecture/adr_enforcement_baseline.json "
        "so the debt baseline reflects reality and can never silently "
        "re-inflate. (Do not edit baseline_snapshot.)"
    )


def test_resolved_adrs_are_genuinely_real_now() -> None:
    """Every id claimed in ``resolved`` must actually classify REAL now — you
    cannot mark a debt paid without having paid it."""
    _, resolved = _load_baseline()
    classes = _classification()
    regressed = sorted(
        n for n in resolved if n in classes and classes[n] is not EnforcementClass.REAL
    )
    assert not regressed, (
        f"ADR(s) {regressed} are listed in `resolved` but no longer classify "
        "REAL — their enforcement regressed. Restore the real asserting check "
        "or move them back out of `resolved`."
    )


def test_exemptions_reference_existing_accepted_adrs() -> None:
    """Every exemption names a real, Accepted ADR with a non-empty
    justification — a typo or a bare id cannot silently widen the allow-list."""
    accepted_numbers = {a.number for a in _accepted()}
    exemptions = _parse_exemptions()
    unknown = sorted(n for n in exemptions if n not in accepted_numbers)
    assert not unknown, (
        f"Exemption(s) name ADR number(s) {unknown} that are not Accepted ADRs "
        "(typo, or a Proposed/Superseded ADR). Exemptions apply only to "
        "Accepted ADRs; fix or remove the entry in "
        "docs/standards/adr_enforcement/exemptions.md."
    )


def test_exempted_adrs_are_not_already_real() -> None:
    """An exemption is only for a decision that legitimately cannot be enforced.
    If the ADR already classifies REAL it needs no exemption — remove it."""
    classes = _classification()
    redundant = sorted(
        n for n in _parse_exemptions() if classes.get(n) is EnforcementClass.REAL
    )
    assert not redundant, (
        f"Exempted ADR(s) {redundant} already classify REAL — an exemption is "
        "only for decisions that cannot carry a resolving check. Remove the "
        "redundant entry from docs/standards/adr_enforcement/exemptions.md."
    )


def test_resolved_and_exempted_are_disjoint() -> None:
    """An ADR is either really enforced (``resolved``) or legitimately
    unenforceable (exempt) — never both."""
    _, resolved = _load_baseline()
    both = sorted(resolved & frozenset(_parse_exemptions()))
    assert not both, (
        f"ADR(s) {both} appear in both `resolved` and the exemptions allow-list "
        "— those lanes are mutually exclusive. A resolved ADR has a REAL check "
        "and needs no exemption; drop it from one lane."
    )


def test_ratchet_is_not_vacuous() -> None:
    """Anti-vacuity: the classifier splits real ADRs across classes and the
    baseline is non-empty, so the gate cannot pass by acting on an empty set."""
    classes = _classification()
    assert classes, "no Accepted ADRs classified — the classifier import is wired wrong"
    assert EnforcementClass.REAL in classes.values(), (
        "no ADR classifies REAL — classify_adr_enforcement is not resolving "
        "checks against the on-disk tree as expected."
    )
    assert _FROZEN_SNAPSHOT, "the frozen debt snapshot must be non-empty."
