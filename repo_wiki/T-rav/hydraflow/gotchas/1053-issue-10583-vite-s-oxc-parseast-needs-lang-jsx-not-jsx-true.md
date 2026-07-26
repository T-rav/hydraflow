---
id: 1053
topic: gotchas
source_issue: 10583
source_phase: plan
created_at: 2026-07-26T02:28:58.639342+00:00
status: active
corroborations: 1
---

# Vite's oxc parseAst needs { lang: 'jsx' }, not { jsx: true }

`src/ui` has no eslint config and no acorn/babel/esbuild in `node_modules` — the only JSX-capable parser available is Vite's re-exported oxc `parseAst`. Passing `{ jsx: true }` throws; the correct option key is `{ lang: 'jsx' }`. Any new source-scanning test (e.g. `src/ui/src/test/borderShorthandScan.js`) that needs to parse `.jsx` files must use this option shape or it will crash on every JSX fixture.

**Why:** the wrong option name fails silently-looking (a thrown parse error) rather than a clear "unsupported option" message, wasting debugging time on scanner tests.
