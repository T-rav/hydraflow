---
id: 0188
topic: dependencies
source_issue: 11228
source_phase: plan
created_at: 2026-08-15T07:17:21.034753+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Vite optimizeDeps.include must list lazy-only bare packages in src/ui

Any bare npm package reachable only through a `lazy(() => import('…'))` boundary in `src/ui/src` must appear in `optimizeDeps.include` in `src/ui/vite.config.mjs`.

- Current include list: `['html2canvas','echarts','echarts-for-react']`
- Eagerly imported packages (e.g. `@xyflow/react`) are exempt
- `echarts` is required whenever `echarts-for-react` is present
- The invariant is pinnable in Python without a node toolchain by parsing the config and walking the import graph

**Why:** Missing entries cause Vite dev-server resolution failures for lazy-loaded routes — the invariant prevents silent regressions when dependencies shift.
