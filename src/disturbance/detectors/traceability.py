"""Untraced-requirement-fraction detector (CH-5, #9733).

Reads the committed traceability matrix artifact and emits one finding per
untraced *percentage point* (the ``<!-- untraced-pct: NN -->`` marker), all
sharing a single signature. Under the standard ``{signature: count}``
baseline this ratchets the fraction itself: the percentage may only shrink
(prune the baseline when it does), and a rise past the baseline blocks.

The committed marker is display-only (CH-5 convergence review finding 3):
``traceability_matrix.md`` is drift-exempt in the arch check (its content
legitimately moves with the git window), so nothing else verifies the
marker. Both :func:`sync_traceability_baseline` and the detector therefore
recompute the fraction from git history through the SAME code path the
generator uses (``arch.generators.traceability_matrix.collect_trace_commits``
+ ``untraced_pct``):

* the baseline only ever LOWERS from the recomputed value — a hand-lowered
  marker cannot ratchet a forgery in;
* a committed marker deviating from the recompute beyond rounding tolerance
  emits a ``marker-mismatch`` finding (stale or tampered — regenerate);
* a recompute that parses ZERO PR-merge commits while the baseline is
  nonzero emits a ``generation-regression`` finding instead of reading as
  0%-untraced success.

Where git history is unavailable or untrustworthy (non-repo checkouts,
shallow CI clones — ``collect_trace_commits`` returns ``None``) the
detector degrades to marker-only mode: the ratchet still counts, the
verification is skipped, and the sync never lowers the baseline.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from arch.generators.traceability_matrix import collect_trace_commits, untraced_pct
from disturbance.baseline import load_baseline
from disturbance.models import Finding

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_ARTIFACT_REL = "docs/arch/generated/traceability_matrix.md"
_BASELINE_REL = "disturbance/baselines/traceability.yaml"
_MARKER_RE = re.compile(r"<!--\s*untraced-pct:\s*(?P<pct>\d+)\s*-->")
#: The default artifact's untraced-pct signature. The detector itself derives
#: every signature from ``self._artifact_rel`` (see ``_untraced_signature``)
#: so an overridden artifact path cannot leave the ceilings it declares
#: pointing at signatures it never emits; this module-level copy exists only
#: for the baseline-sync helper, which is bound to the default artifact.
_SIGNATURE = f"{_ARTIFACT_REL}::untraced-pct"

#: The largest untraced-pct count this detector will ever materialise, and
#: therefore the ceiling it declares to the gate (``reachable_ceilings``).
#:
#: The marker's LEGITIMATE domain is 0..100, and the baseline landed at 100
#: (#9733: zero Req-ID adoption, so every commit in the window is untraced).
#: Capping the emitted count at exactly 100 — which ``min(pct, 100)`` did —
#: made the block-new arm arithmetically dead: ``cur > base`` could not hold
#: for ANY marker value, so doubling the committed debt to 150 left the gate
#: green. Worse, the clamp ran BEFORE the marker-mismatch cross-check, so a
#: forged 150 was laundered into a 100 that matched the recompute exactly and
#: the tamper detector saw nothing either.
#:
#: The bound that remains is a MATERIALISATION bound, not a measurement one:
#: ``detect`` emits one Finding per percentage point, so an unbounded marker
#: is an out-of-memory vector. Ten times the legitimate domain is far enough
#: above any honest value that nothing real is truncated, and far enough
#: above the baseline that the block-new arm has a non-empty failing region.
#: It is ONE constant so the clamp and the declared ceiling cannot drift
#: apart — a ceiling that disagreed with the clamp would be the same defect
#: one level up.
_MAX_EMITTED_PCT = 1000

#: Allowed |committed - recomputed| gap before the mismatch finding fires.
#: The pct is ceiled, and the commit window legitimately shifts by a few
#: squash-merges between the author's regen and the gate run — one point
#: absorbs that jitter without giving forgeries any useful headroom.
_MARKER_TOLERANCE_PCT = 1


class TraceabilityDetector:
    name = "traceability"

    def __init__(self, artifact_rel: str = _ARTIFACT_REL) -> None:
        self._artifact_rel = artifact_rel

    def detect(self, repo_root: Path) -> list[Finding]:
        path = repo_root / self._artifact_rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []  # no matrix artifact → dimension is inert
        match = _MARKER_RE.search(text)
        if match is None:
            return []
        committed_pct = int(match.group("pct"))
        # Bound only what is MATERIALISED; the verifier below still sees the
        # value the artifact actually claims, so a forged marker cannot be
        # normalised into agreement with the recompute.
        pct = min(committed_pct, _MAX_EMITTED_PCT)
        finding = Finding(
            dimension=self.name,
            path=self._artifact_rel,
            signature=self._untraced_signature,
            message=(
                f"{committed_pct}% of recent PR-merge commits carry no Req-ID "
                "line (requirements-traceability adoption ratchet)"
            ),
        )
        findings = [finding] * pct
        verification = self._verify_marker(repo_root, committed_pct=committed_pct)
        if verification is not None:
            findings.append(verification)
        return findings

    @property
    def _untraced_signature(self) -> str:
        return f"{self._artifact_rel}::untraced-pct"

    @property
    def _mismatch_signature(self) -> str:
        return f"{self._artifact_rel}::marker-mismatch"

    @property
    def _regression_signature(self) -> str:
        return f"{self._artifact_rel}::generation-regression"

    def reachable_ceilings(self) -> Mapping[str, int]:
        """Every signature this detector emits is capped, and by how much.

        ``untraced-pct`` is capped by the materialisation bound; the two
        verification signatures are single findings, so their ceiling is 1.
        Declaring them all is what lets ``run_gate`` refuse a baseline that
        has climbed to where its own block-new arm can no longer fire.
        """
        return {
            self._untraced_signature: _MAX_EMITTED_PCT,
            self._mismatch_signature: 1,
            self._regression_signature: 1,
        }

    def _verify_marker(self, repo_root: Path, *, committed_pct: int) -> Finding | None:
        """Recompute the fraction and flag a stale/tampered/regressed marker."""
        commits = collect_trace_commits(repo_root)
        if commits is None:
            return None  # no trustworthy history → marker-only mode
        if not commits:
            if self._baseline_count(repo_root) > 0:
                return Finding(
                    dimension=self.name,
                    path=self._artifact_rel,
                    signature=self._regression_signature,
                    message=(
                        "traceability recompute parsed ZERO PR-merge commits "
                        "from git history while the ratchet baseline is "
                        "nonzero — generation regression (the matrix "
                        "generator is matching nothing), NOT 0% untraced; "
                        "do not trust the committed marker"
                    ),
                )
            return None
        recomputed = untraced_pct(commits)
        if abs(recomputed - committed_pct) > _MARKER_TOLERANCE_PCT:
            return Finding(
                dimension=self.name,
                path=self._artifact_rel,
                signature=self._mismatch_signature,
                message=(
                    f"committed untraced-pct marker ({committed_pct}%) "
                    f"deviates from the fraction recomputed from git history "
                    f"({recomputed}%) — matrix stale or tampered; regenerate "
                    "via make arch-regen"
                ),
            )
        return None

    @staticmethod
    def _baseline_count(repo_root: Path) -> int:
        return load_baseline(repo_root / _BASELINE_REL).get(_SIGNATURE, 0)


def _recomputed_pct(repo_root: Path) -> int | None:
    """The recomputed untraced pct, or ``None`` when it must not be trusted.

    ``None`` covers BOTH unavailable history (non-repo / shallow clone) and
    an empty parse (zero PR-merge commits — the generation-regression shape,
    which must never read as a genuine 0%).
    """
    commits = collect_trace_commits(repo_root)
    if not commits:
        return None
    return untraced_pct(commits)


def sync_traceability_baseline(repo_root: Path) -> bool:
    """Prune the traceability baseline to the RECOMPUTED untraced pct.

    The matrix and the ratchet baseline are two views of one number: when
    a regen (``make arch-regen`` / ``DiagramLoop``) commits a matrix with
    a lower untraced fraction than the baseline count, the gate's
    ``resolved`` assertion would fail on the next unrelated PR unless the
    baseline shrinks in the same change. This helper keeps them in
    lockstep.

    The pct is recomputed from git history via the generator's own code
    path — the committed ``<!-- untraced-pct: NN -->`` marker is
    display-only and only gates adoption (present = dimension adopted), so
    a hand-edited marker can never lower the baseline (CH-5 convergence
    review finding 3). Ratchet-preserving by construction: the baseline
    count only ever moves DOWN; a recompute above the baseline is left
    alone so the gate still blocks growth as ``new``. Missing artifact,
    missing marker, missing baseline file, unavailable git history
    (non-repo / shallow clone), or an empty recompute (generation
    regression — zero PR-merge commits parsed) are all inert.

    Returns True when the baseline file was rewritten.
    """
    artifact = repo_root / _ARTIFACT_REL
    baseline_path = repo_root / _BASELINE_REL
    try:
        text = artifact.read_text(encoding="utf-8")
        raw = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    if _MARKER_RE.search(text) is None:
        return False  # marker presence = adoption signal; value unused

    entries = dict(raw.get("entries") or {})
    if _SIGNATURE not in entries:
        return False
    current = int(entries[_SIGNATURE])

    # None = unverifiable (no history) OR generation-regression empty parse —
    # either way, never lower the baseline on the marker's word alone.
    pct = _recomputed_pct(repo_root)
    if pct is None or pct >= current:
        return False  # equal → nothing to do; higher → the gate must block it

    if pct == 0:
        del entries[_SIGNATURE]
    else:
        entries[_SIGNATURE] = pct
    raw["entries"] = entries
    baseline_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return True
