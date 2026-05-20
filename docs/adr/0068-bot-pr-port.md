# ADR-0068 — BotPRPort: Minimal Interface for Caretaker Bot-PRs

**Status:** Proposed
**Date:** 2026-05-19
**Enforced by:** (none) — structural subtype check planned in follow-up

## Context

Several caretaker loops (`TermProposerLoop`, `TermPrunerLoop`) need to open
auto-merging bot PRs to push glossary changes. The full `PRPort` surface is
very wide (50+ methods for PR lifecycle, label management, CI polling, issue
management, etc.). Caretaker loops only need a single operation: "create a
branch, commit files, open a PR with given labels, return the PR number."

Forcing these loops to depend on `PRPort` made their tests heavier (had to
mock the full port) and their intent less clear (which of the 50 methods do
they actually use?).

## Decision

Define `BotPRPort` as a local `Protocol` in `src/term_proposer_loop.py` with
exactly one method:

```python
async def open_bot_pr(
    *, branch, title, body, labels, files
) -> int: ...
```

Production wiring provides a thin adapter that composes `PRPort.push_branch` +
`PRPort.create_pr` + `PRPort.add_pr_labels` behind this single call. Tests
pass a `MagicMock(spec=BotPRPort)` with `open_bot_pr` scripted to return a PR
number. `TermPrunerLoop` imports `BotPRPort` from `term_proposer_loop` to
avoid defining it twice.

## Consequences

- Caretaker loop tests are lighter — only one method to script.
- The port is co-located with its primary consumer rather than cluttering `src/ports.py` with a very narrow interface.
- Adding a new caretaker loop that opens bot-PRs should reuse `BotPRPort` from `term_proposer_loop` rather than defining a third Protocol.

## Alternatives considered

- **Use full PRPort.** Works but couples caretaker tests to a very wide mock surface; intent is obscured.
- **Inline the push_branch + create_pr calls.** No abstraction, difficult to test the loop's reaction to PR-open failure.

## Related

- `src/term_proposer_loop.py:BotPRPort` — the port definition
- `src/term_pruner_loop.py:TermPrunerLoop` — second consumer
- [ADR-0054](0054-term-auto-proposer-loop.md) — TermProposerLoop
- [ADR-0057](0057-term-pruner-loop.md) — TermPrunerLoop
