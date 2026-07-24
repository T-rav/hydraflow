---
id: 0159
topic: architecture
source_issue: 10388
source_phase: plan
created_at: 2026-07-24T04:39:16.271095+00:00
status: active
corroborations: 1
---

# Docs-only ADR-drift repair avoids retriggering the touchpoint auditor

A repair PR that only edits `docs/adr/*.md` and `docs/arch/generated/*` (no `src/` module changes) cannot itself trigger new touchpoint drift, so it's safe to close ADR-drift tracking issues without touching implementation code.

Example: issue #10388's repair for fleet PR #10376 modifies only `docs/adr/0059-*.md`, `0094-*.md`, `0095-*.md`, `0102-*.md`, `README.md`, and regenerated `adr_xref.md`/`adr-conformance.md`/`.meta.json` — zero `src/` deltas.

**Why:** keeps the scope guard tight and prevents a repair PR from re-entering the same drift-detection loop it's meant to close out.
