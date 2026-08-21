"""Token-drift filing helpers — the pure half of #11442's actuator.

``ErosionMetricsLoop`` hosts the check (its daily tick calls
``token_drift.load_and_check_drift``); these helpers turn the resulting
``DriftReport`` into REGULAR finding candidates — one per drifting chart per
ISO week, fingerprinted ``token_drift:<source>:<window_key>`` — and render the
``hydraflow-find`` issue. Not a class issue: each source+week is its own
episode, so the candidates ride the loop's ``_file_findings`` path (dedup by
fingerprint) rather than the mass/suite-hygiene class reconciler.

No I/O, no filing here. ``sigma`` and the verdict come from the engine
(``token_drift.check_drift``, ADR-0133 widened-limit band); nothing in this
module re-derives the band.
"""

from __future__ import annotations

from typing import Any

from token_drift import MEDIAN_TOKENS_SOURCE, DriftReport, DriftStatus

TOKEN_DRIFT_KIND = "token_drift"


def token_drift_fingerprint(source: str, window_key: str) -> str:
    """Dedup key for one drift episode: ``token_drift:<source>:<ISO week>``."""
    return f"{TOKEN_DRIFT_KIND}:{source}:{window_key}"


def token_drift_candidates(report: DriftReport) -> list[dict[str, Any]]:
    """One regular candidate per DRIFTING chart of an ``OK`` report.

    A non-``OK`` status (no/thin/stale baseline, idle trailing week) carries
    no verdict and yields nothing; so does a report without a ``window_key``
    — there would be no week to fingerprint the episode on.
    """
    if report.status is not DriftStatus.OK or not report.window_key:
        return []
    window_key = report.window_key
    return [
        {
            "kind": TOKEN_DRIFT_KIND,
            "fingerprint": token_drift_fingerprint(chart.source, window_key),
            "source": chart.source,
            "before_share": chart.before_share,
            "after_share": chart.after_share,
            "sigma": chart.sigma,
            "window_key": window_key,
        }
        for chart in report.sources
        if chart.is_drifting
    ]


def token_drift_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """The ``_do_work`` result entry: the week checked and who drifted in it."""
    return {
        "window_key": candidates[0]["window_key"] if candidates else None,
        "drifting": [c["source"] for c in candidates],
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _count(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f}"


def _sigma_text(sigma: float | None) -> str:
    # A perfectly flat baseline has σ̂ = 0: any rise breaches, but "how many
    # sigma" is undefined — say so rather than print a division by zero.
    return "σ n/a" if sigma is None else f"{sigma:.1f}σ"


def render_token_drift(candidate: dict[str, Any]) -> tuple[str, str]:
    """Render (title, body) for one token-drift episode, evidence table included."""
    source: str = candidate["source"]
    window_key: str = candidate["window_key"]
    sigma_text = _sigma_text(candidate["sigma"])
    if source == MEDIAN_TOKENS_SOURCE:
        subject = "median tokens per issue"
        before = _count(candidate["before_share"])
        after = _count(candidate["after_share"])
    else:
        subject = f"`{source}` share"
        before = _pct(candidate["before_share"])
        after = _pct(candidate["after_share"])
    title = (
        f"Token drift: {subject} {before} → {after} ({sigma_text}) in week {window_key}"
    )
    body = (
        "## Evidence (ErosionMetricsLoop, automated)\n\n"
        "| metric | value |\n|---|---|\n"
        f"| chart | `{source}` |\n"
        f"| ISO week | {window_key} |\n"
        f"| baseline centre | {before} |\n"
        f"| observed | {after} |\n"
        f"| sigma | {sigma_text} |\n"
        "| verdict | drifting |\n\n"
        "## How to read this\n\n"
        "`token_drift` (#11441) rolls the trailing complete ISO week's "
        "`inferences.jsonl` into each source's share of fleet tokens (plus the "
        "fleet's median tokens per issue) and tests every chart against the "
        "pinned baseline (`scripts/pin_token_baseline.py`) with the vitals "
        "fleet's widened-limit band (ADR-0133): a chart drifts when its reading "
        "exceeds centre + L·σ̂, where σ̂ is the baseline's moving-range "
        "dispersion and L widens with the chart count. A rising share means "
        "this phase now takes a larger slice of every issue's token budget — "
        "usually a prompt that grew, a retry loop, or a phase spawning more "
        'often than it used to; "σ n/a" means the baseline was perfectly '
        "flat, so any rise breaches. Filed once per chart per ISO week "
        "(fingerprint `token_drift:<source>:<week>`); a filing that fails is "
        "re-derived and retried on the loop's next tick. Pattern B outer-loop "
        "finding: it "
        "reports, it never prunes a prompt or edits config — if the new level "
        "is intended, re-pin the baseline.\n"
    )
    return title, body
