---
id: 0201
topic: architecture
source_issue: 10488
source_phase: plan
created_at: 2026-07-24T21:53:09.549120+00:00
status: active
corroborations: 1
---

# New StreamView.jsx logic goes in src/ui/src/utils/, not inline

`src/ui/src/components/StreamView.jsx` is already 741 lines; new pure-derivation logic (counts, aggregates, formatting) belongs in a new module under `src/ui/src/utils/` (e.g. `pipelineCounts.js`) with tests in `utils/__tests__/`, and the component only calls the util and renders the result. Also: badge/inline styles in this file are pre-computed at module scope, not spread inline inside a `.map()` in `PipelineFlow`'s render loop.

**Why:** keeps StreamView.jsx from growing further and keeps derivation logic independently unit-testable without mounting the component.
