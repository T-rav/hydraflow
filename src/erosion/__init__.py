"""Erosion sensors — outer-loop structural-drift measurements (ADR-0099 open surface, epic #10104).

Distinct from `disturbance` (ADR-0101/0104): the disturbance dampener's
`ViolationDetector.detect(repo_root)` is a per-file static snapshot of the
repo as it is now. Erosion sensors are change-scoped — they measure how a
merged change ripples across the codebase (module spread, concept scatter),
which that repo-static protocol can't express. See #10105 for the first
sensor (change-spread / shotgun-surgery).
"""
