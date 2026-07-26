# ADR-Enforcement Exemptions (allow-list)

This is the machine-parseable allow-list of Accepted ADRs that are permitted to
classify `WEAK` or `MISSING` **without** counting against the enforcement-debt
ratchet — because the decision is *genuinely* process-only and cannot be bound
to a resolving, asserting check.

An exemption is **not** a way to defer work. It is a permanent, justified
statement that "this decision has no machine-checkable invariant." Reach for it
only after concluding no real check is feasible (see
[`README.md`](README.md) — "When an exemption is legitimate"). Debt that *can*
be enforced belongs in the ratchet baseline
(`tests/architecture/adr_enforcement_baseline.json`), not here.

Seeded **empty**: at ratchet landing every one of the 12 debt ADRs is in the
baseline (to burn down), and nothing is exempt. Exemptions are added one at a
time, each with a one-line justification, as the backfill work concludes a given
ADR is process-only.

## Format (normative)

`tests/architecture/test_adr_enforcement_ratchet.py` parses this file for entry
lines of exactly this shape (one per ADR, anywhere in the "Active exemptions"
list below):

```
- ADR-NNNN: <one-line justification of why no real check is feasible>
```

- `NNNN` is the zero-padded ADR number.
- The justification must be non-empty — a bare id with no reason fails the gate.
- Prose that merely *mentions* an ADR elsewhere in this file is ignored; only
  lines matching the `- ADR-NNNN: ...` bullet shape are treated as entries.
- An exempted ADR must be an existing **Accepted** ADR and must **not** already
  classify `REAL`. If it is `REAL`, it needs no exemption — remove the entry.
- An id may live in the exemption list **or** in the baseline's `resolved`
  list, never both.

## Active exemptions

_(none — seeded empty; see the baseline for the current debt set)_
