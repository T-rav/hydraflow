---
id: 0622
topic: patterns
source_issue: 10626
source_phase: plan
created_at: 2026-07-26T11:57:17.619587+00:00
status: active
corroborations: 1
---

# Mark agent/CI-rendered overlays data-sensitive per ADR-0018

Any overlay rendering agent- or CI-produced content must carry `data-sensitive="true"` so html2canvas capture redacts it. `SENSITIVE_SELECTORS` in `src/ui/src/constants.js` already covers `[data-sensitive]`, so no selector change is needed.

Example: `ImageLightbox`'s root overlay div sets `data-sensitive="true"` because it renders `PRManager.upload_screenshot` gist URLs.

**Why:** Per ADR-0018 §1, unredacted agent-produced images leak into dashboard screenshots captured for reports.
