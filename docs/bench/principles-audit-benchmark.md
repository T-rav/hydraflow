# `make audit` runtime benchmark

Captured: 2026-04-22
Runs: 5
Host: Darwin mac.lan 25.3.0 Darwin Kernel Version 25.3.0: Wed Jan 28 20:56:34 PST 2026; root:xnu-12377.91.3~2/RELEASE_ARM64_T8112 arm64

| Run | Wall-clock (s) |
|---|---|
| 1 | 3.66 |
| 2 | 3.52 |
| 3 | 3.52 |
| 4 | 3.80 |
| 5 | 3.68 |

**p50:** 3.66s
**p95:** 3.80s

**Budget:** 30s (spec §4.4 "Runtime budget for the CI gate").

**Decision:**
- p95 ≤ 30s → add `audit` job to `.github/workflows/ci.yml` (Task 17a).
- p95 > 30s → add `audit` job to `.github/workflows/rc-promotion-scenario.yml` instead (Task 17b).

**Selected:** ci.yml

**Rationale:** Measured p95 of 3.80s is ~8x under the 30s per-PR budget. Running `make audit` on every PR gives fastest feedback with negligible CI cost. Task 17a applies.

## Notes

- `make audit` exits non-zero today (Error 1) due to a real WARN finding: P5.5 reports `main` branch on `T-rav/hydraflow` lacks branch protection (HTTP 404 from `gh`). This is a legitimate audit signal, not a prerequisite gap. The CI job will need to tolerate WARN exit codes or the underlying protection must be enabled — to be resolved in Task 17a wiring.
- Wall-clock was captured via `/usr/bin/time -p make audit > /dev/null 2>bench-$i.txt` per plan Task 0 Step 1.
- Runtime variance across 5 runs is ~0.28s (7%), well within a single CI-budget bucket; no additional warmup runs needed.
