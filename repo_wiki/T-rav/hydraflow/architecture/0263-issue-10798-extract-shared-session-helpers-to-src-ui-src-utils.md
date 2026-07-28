---
id: 0263
topic: architecture
source_issue: 10798
source_phase: plan
created_at: 2026-07-28T10:05:46.407746+00:00
status: active
corroborations: 1
---

# Extract shared session helpers to `src/ui/src/utils/sessions.js`

When two modules need identical logic (e.g. `SessionSidebar.jsx` and `factoryStartMs` in `vitals.js` both pick the latest session), extract to `src/ui/src/utils/sessions.js` and export without underscore prefix. The shared `pickLatestSession` must NOT filter by status — callers filter before calling.

- `SessionSidebar.jsx`: delete local copy, import shared one.
- `vitals.js`: filter to `status === 'active'` then call helper.

**Why:** Module-private copies drift; the sidebar's correct max-by-`started_at` logic existed but `factoryStartMs` used a broken `.find()` because the logic was duplicated rather than shared.
