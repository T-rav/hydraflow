---
id: 0578
topic: patterns
source_issue: 10592
source_phase: plan
created_at: 2026-07-26T03:33:58.716456+00:00
status: active
corroborations: 1
---

# Header.jsx had a dead sr-only class — check src/ui for defined CSS before using it

`Header.jsx:284` rendered an `sr-only`-classed span whose class was never defined anywhere in `src/ui`, making it visually hidden by accident (no actual CSS) rather than by an intentional accessibility utility. Before applying a utility class like `sr-only` in `src/ui/src/components/`, grep for its definition (global CSS, Tailwind config, styled-components theme) — don't assume common utility class names exist just because they're conventional elsewhere.

**Why:** an undefined a11y class silently fails to hide content from sighted users while giving false confidence that a screen-reader-only contract is in place.
