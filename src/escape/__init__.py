"""Escape-ledger instruments — the outer-loop falsification measurement (#10367).

The factory publishes two claims its own instruments cannot otherwise check:
that defects escaping the gauntlet are rare and get encoded, and that
codebase-scale entanglement is flat rather than growing. This package holds
the FIRST half — the **escape ledger** — the append-only record that links a
defect discovered *after* merge back to the change that shipped it (escape
rate, time-to-detection, attribution, encoding closure).

An **escape** is a defect discovered AFTER a change passed the gauntlet and
merged to the base branch (gate-escape framing, decided in the spec
``docs/proposals/escape-ledger-and-erosion-trends.md``): pre-merge catches
and immediate main-CI breaks are the gates functioning and are explicitly
NOT escapes.

Layered like the sibling ``erosion`` package (mirror-the-style, don't
cross-import): ``models`` (value objects), ``detect`` (pure detection over
explicit commit inputs + a thin git adapter), ``attribution`` (pure
mechanical attribution), ``ledger`` (append-only JSONL store), ``metrics``
(pure rate/time-to-detection/encoding rollups), ``report`` (markdown render).
The consuming caretaker is ``escape_ledger_loop.EscapeLedgerLoop`` — a
read-only ADR-0029 Pattern-B sensor that records, never fixes and never
gates (the escape already became work through normal triage; the ledger is
bookkeeping ABOUT the instruments, not one of them).
"""
