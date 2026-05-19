# ADR-0070 — ReviewInsightStorePort: Persistence Boundary for Review Feedback Patterns

**Status:** Proposed
**Date:** 2026-05-19
**Enforced by:** (none) — structural subtype check planned for `tests/test_ports.py` in follow-up

## Context

`ReviewPhase` tracks recurring reviewer-feedback categories (missing tests, error handling, naming, etc.) by persisting `ReviewRecord` objects to a JSONL file via `ReviewInsightStore`. The concrete store carries file-system concerns (JSONL rotation, atomic writes, backup management) and a `DedupStore` for idempotent proposal tracking.

Without a port, `ReviewPhase` depended directly on `ReviewInsightStore`, coupling the phase to the file-storage implementation and making unit tests heavier (they had to supply a real or stub `ReviewInsightStore` instead of a lightweight mock).

## Decision

Define `ReviewInsightStorePort` as a `@runtime_checkable Protocol` in `src/ports.py` with the seven methods that `ReviewPhase` actually calls:

- `append_review(record)` — persist a completed review
- `load_recent(n)` — fetch the last *n* review records
- `get_proposed_categories()` — return categories that have already triggered a mandatory-block proposal
- `mark_category_proposed(category)` — record that a category has been proposed
- `record_proposal(category, pre_count)` — log a proposal with its baseline count
- `load_proposal_metadata()` — load proposal state for all categories
- `update_proposal_verified(category, *, verified)` — mark whether the proposed block reduced the pattern

`ReviewInsightStore` satisfies this port via structural subtyping.

## Consequences

- `ReviewPhase` unit tests can use `MagicMock(spec=ReviewInsightStorePort)` with only the called methods scripted.
- The JSONL storage backend can be replaced (e.g. with a database-backed store) without touching `ReviewPhase`.
- The `update_proposal_verified` keyword argument (`verified=`) must always be passed as a keyword; callers cannot rely on positional binding.

## Alternatives considered

- **Pass `ReviewInsightStore` directly.** Simple but ties the phase to the concrete storage implementation.
- **Separate read and write ports.** Over-engineering for a port with a single consumer.

## Related

- `src/ports.py:ReviewInsightStorePort` — the port definition
- `src/review_insights.py:ReviewInsightStore` — the concrete adapter
- [ADR-0044](0044-hydraflow-principles.md) — four-layer architecture
