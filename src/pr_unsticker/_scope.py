"""What the PR unsticker may merge on a standing grant (#11970).

The unsticker fixes a HITL-stuck PR, waits for CI, and merges — presenting the
operator-enabled ``unstick_auto_merge`` config grant as an operator-role
approval. That grant is a statement about the LANE ("the factory may unstick
itself"), not about the PR, and the PR is somebody else's work.

It went unnoticed because the packaged `policy.yaml` declares `paths: []` and
`labels: []` on every class, so `MergePolicy.has_change_matchers` is False, the
gate never fetches the diff, and `classify_change` returns the `default: true`
class — `tractable-reversible`, `autonomy: act`, no approvals required. The
`high-blast-radius` class, the only one carrying `required_approvals`, cannot
match anything and never fires. Green CI was the entire test.

This is the LANE's own scope, deliberately not a fix to that policy: giving
`high-blast-radius` real matchers changes what every merge lane in the factory
requires, and that is a throughput decision for the operator, not a side effect
of repairing one loop. Recorded on #11970.

Governance surfaces only. The unsticker's job is unwedging mechanical failures,
so a PR that also rewrites the rules, the gates, or the decision record is
outside what "the factory may unstick itself" can honestly cover.
"""

from __future__ import annotations

#: Paths a standing lane grant cannot speak for. Kept narrow on purpose: this
#: is not "everything risky", it is "changes to the rules themselves", which is
#: the one class a lane-level grant can never be evidence about.
OUT_OF_SCOPE_PREFIXES: tuple[str, ...] = (
    "docs/adr/",
    "docs/standards/",
    "control/",
    ".github/workflows/",
)


def out_of_scope(paths: list[str]) -> list[str]:
    """Changed paths the unsticker's standing grant cannot authorise.

    Returns the offending paths so the HITL message can name them — a release
    that says only "out of scope" makes a human re-derive what this already
    knows.
    """
    return sorted(path for path in paths if path.startswith(OUT_OF_SCOPE_PREFIXES))
