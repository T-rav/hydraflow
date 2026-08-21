"""Classify failed implement runs into a small set of failure classes (#11593).

The August-2026 manifest audit found 61 of 105 failed implement runs died at
the test-adequacy gate — but nothing surfaced that split, so the regression
was found by a manual audit weeks later. This module gives every failed run a
failure class at the point the result is classified (``ImplementPhase``), so
the counts flow into the run manifest (``RunManifest.failure_class``) and the
session counters the System tab reads (``PipelineStats.implement_failures``).

Pure string classification — no imports from the rest of the codebase, so the
state layer and the implement phase can both use it without cycles.
"""

from __future__ import annotations

#: The closed set of failure classes (#11593 seam 3). ``other`` is the
#: catch-all; keep the set stable — dashboards and manifest audits key on it.
FAILURE_CLASSES: tuple[str, ...] = (
    "test_adequacy",
    "timeout",
    "zero_commit",
    "diff_sanity",
    "quality",
    "scope",
    "other",
)

#: Ordered (needle, class) rules. First match wins. Quality-gate summaries are
#: checked before the generic timeout needle so "`make quality-lite` timed out
#: after 600s" counts as a quality failure, not an agent timeout.
_RULES: tuple[tuple[str, str], ...] = (
    ("test-adequacy failed", "test_adequacy"),
    ("diff-sanity failed", "diff_sanity"),
    ("scope-check failed", "scope"),
    ("No commits found on branch", "zero_commit"),
    ("quality", "quality"),
    ("`make", "quality"),
    ("test-impacted", "quality"),
    # ``runner_utils`` raises RuntimeError("Agent process timed out after Ns");
    # AgentRunner.run stores repr(exc), so match by substring.
    ("timed out", "timeout"),
)


def classify_implement_failure(error: str | None) -> str:
    """Map a failed run's error string to one of :data:`FAILURE_CLASSES`.

    ``error`` is ``WorkerResult.error`` — the manifest error string. Unknown
    or empty errors classify as ``"other"``; this never raises.
    """
    if not error:
        return "other"
    for needle, failure_class in _RULES:
        if needle in error:
            return failure_class
    return "other"
