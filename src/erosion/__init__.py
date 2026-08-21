"""Erosion sensors — outer-loop structural-drift measurements (ADR-0099 open surface, epic #10104).

Distinct from `disturbance` (ADR-0101/0104): the disturbance dampener's
`ViolationDetector.detect(repo_root)` is a per-file static snapshot of the
repo as it is now. Erosion sensors are change-scoped — they measure how a
merged change ripples across the codebase (module spread, concept scatter),
which that repo-static protocol can't express. See #10105 for the first
sensor (change-spread / shotgun-surgery) and #10106 for the second
(concept-scatter / duplication — a v1, provisional heuristic; see
`erosion.scatter`'s module docstring).

Two whole-tree sensors sit beside the change-scoped ones: `erosion.mass`
(god files / god classes by size, ratcheted by
`tests/architecture/test_mass_ratchet.py`) and `erosion.suite_hygiene`
(parametrize candidates / cross-file duplicate tests, ratcheted by
`tests/architecture/test_suite_hygiene_ratchet.py`). Both file ONE standing
class issue each through `ErosionMetricsLoop` — the "always keep decomposing /
always keep pruning" pressure — while the ratchets stop new offenders at PR
time. `erosion.token_drift_filing` is the pure half of the token-share drift
actuator (#11442): it turns `token_drift`'s weekly verdict into one regular
`hydraflow-find` candidate per drifting source per ISO week, filed by the same
loop.
"""
