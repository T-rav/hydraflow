"""Regression (#10010): cancelled-at-timeout CI jobs were invisible to
GateHealthLoop, so the factory blindly retried into repeat hangs.

2026-07-19: PRs #9983 and #10002 hung the CI ``Tests`` job — CANCELLED at
~the workflow's ``timeout-minutes`` with ZERO FAILED lines. That is not a
red-check distribution (``tally_job_stats`` explicitly drops ``cancelled``
conclusions), so nothing in GateHealthLoop (#9974) ever flagged it; the
factory just retried into the same wedge. Root cause both times: a test
mocked a subprocess's ``.pid`` (defaulting to ``1``), and the code under
test fed that straight into a real ``os.killpg`` — which reached the CI
container's own PID 1. Diagnosis REQUIRED a Linux container: macOS raises a
benign ``EPERM`` on the same call, so every local repro passed clean.

``find_suspected_hangs`` must classify exactly this shape — job conclusion
CANCELLED, duration within tolerance of the job's configured
``timeout-minutes``, a test-named step that never reached a terminal
conclusion — as a distinct ``suspected_hang`` verdict, separate from every
other GateHealthLoop finding kind, so the rendered issue carries the
bounded-local/Linux-container repro playbook instead of nothing at all.
"""

from __future__ import annotations

from gate_health_loop import (
    find_suspected_hangs,
    finding_fingerprint,
    tally_job_stats,
)

_HANGING_TESTS_JOB = {
    "name": "Tests",
    "conclusion": "cancelled",
    "run_id": 9983,
    "pr_number": 9983,
    "started_at": "2026-07-18T00:00:00Z",
    "completed_at": "2026-07-18T00:30:02Z",  # 1802s vs. a 30m (1800s) timeout
    "steps": [
        {"name": "Install dependencies", "conclusion": "success"},
        # The step never reached success/failure/skipped: the runner was
        # killed mid-test, not after it — zero FAILED lines to read.
        {"name": "Run tests with coverage", "conclusion": None},
    ],
}


def test_cancelled_at_timeout_job_is_invisible_to_the_distribution_tally() -> None:
    # Confirms the ORIGINAL bug premise still holds: this job shape
    # contributes nothing to born-broken/blame-correlation stats. The fix
    # is an ADDITIONAL classifier, not a change to this exclusion.
    stats = tally_job_stats([_HANGING_TESTS_JOB])
    assert stats == {}


def test_cancelled_at_timeout_with_unfinished_step_is_suspected_hang() -> None:
    findings = find_suspected_hangs(
        [_HANGING_TESTS_JOB],
        timeout_minutes_by_job={"Tests": 30},
        tolerance_seconds=90,
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding["kind"] == "suspected_hang"
    assert finding["check"] == "Tests"
    assert finding["unfinished_step"] == "Run tests with coverage"


def test_a_second_unrelated_hang_on_the_same_check_still_gets_its_own_issue() -> None:
    # #9983 and #10002 are two DISTINCT incidents on the same "Tests" job.
    # A fingerprint keyed on check name alone (like the structural findings)
    # would silently drop the second one after the first was filed.
    first = finding_fingerprint(
        {"kind": "suspected_hang", "check": "Tests", "run_id": 9983}
    )
    second = finding_fingerprint(
        {"kind": "suspected_hang", "check": "Tests", "run_id": 10002}
    )
    assert first != second


def test_duration_far_from_timeout_is_a_normal_cancellation_not_a_hang() -> None:
    early_cancel = dict(_HANGING_TESTS_JOB, completed_at="2026-07-18T00:01:30Z")
    findings = find_suspected_hangs(
        [early_cancel],
        timeout_minutes_by_job={"Tests": 30},
        tolerance_seconds=90,
    )
    assert findings == []
