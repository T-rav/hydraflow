---
id: 1028
topic: gotchas
source_issue: 10564
source_phase: plan
created_at: 2026-07-25T23:31:13.809610+00:00
status: superseded
corroborations: 1
superseded_by: 1039
---

# jsdom doesn't parse CSS-var border shorthand — assert React's written longhands instead

Theme border values in `Header.jsx` use CSS custom properties (`border: '1px solid var(--border)'`); jsdom's CSSOM may not decompose this shorthand the way a real browser does. Regression and unit assertions should check `style.borderColor` / `style.borderWidth` (the longhands React actually writes to the DOM node), not `style.border` itself.

**Why:** asserting on `style.border` directly can pass or fail based on jsdom's CSS parsing quirks rather than the actual bug being tested.
