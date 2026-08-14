---
id: 0152
topic: dependencies
source_issue: 11113
source_phase: plan
created_at: 2026-08-14T09:30:40.586461+00:00
status: active
corroborations: 1
---

# Route make UI targets through ui-npm.sh for CI entry-point parity

`make smoke` (`Makefile:268`) and the quality UI lane both run via `scripts/ui-npm.sh test`; `src/ui/package.json`'s `test` script is `node ./scripts/run-vitest.cjs run`, matching CI's `npm test` (`ci.yml:703`). Do not shortcut to raw `npx vitest` in the Makefile.

**Why:** Bypassing the helper breaks the entry-point parity asserted by the #9875 counter-pin and masks vitest's real exit code behind a pipeline.
