---
id: 1456
topic: testing
source_issue: 10762
source_phase: plan
created_at: 2026-07-28T00:37:27.487485+00:00
status: active
corroborations: 1
---

# Bare-cite resolution is presence-based, not symbol-lookup

Rule: Use presence in an identifier corpus to resolve Style-D bare cites, not symbol lookup. A bare backticked token like `wiki_lesson_coverage` has no module/symbol half, so `verify_cite_ast` cannot resolve it. `build_symbol_corpus` harvests tokens from `src/`, `scripts/`, `tests/`, `src/ui/src` under `repo_root`; `resolve_bare_cite` checks membership. This keeps string-literal identifiers like `left_on_primary` green while dead references go red.

**Why:** Symbol-lookup rules cannot disambiguate a bare token, causing false positives on correct cites that exist only as string literals or file stems.
