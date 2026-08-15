---
id: 2307
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.986842+00:00
status: superseded
corroborations: 1
supersedes: 2162
superseded_by: 2497
---

# Bare-cite resolution is presence-based, not symbol-lookup

Use presence in an identifier corpus to resolve Style-D bare cites, not symbol lookup. A bare backticked token like `wiki_lesson_coverage` has no module/symbol half, so `verify_cite_ast` cannot resolve it. `build_symbol_corpus` harvests tokens from `src/`, `scripts/`, `tests/`, `src/ui/src` under `repo_root`; `resolve_bare_cite` checks membership.

**Why:** Symbol-lookup rules cannot disambiguate a bare token, causing false positives on correct cites that exist only as string literals or file stems.
