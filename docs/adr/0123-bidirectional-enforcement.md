# ADR-0123: Bidirectional enforcement — every rule declares which direction it binds

- **Status:** Proposed
- **Date:** 2026-07-30
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/test_adr_direction_declared.py`
- **Binds:** both
- **Addresses:** #10849 (bidirectional enforcement), #10851 (self-modification class breadth)

> **This is a Proposed ADR — a design ruling for decision.** The four
> principle-level decisions below were already ruled by the author (2026-07-30);
> this records them as canon and wires the mechanical backstop. Accept, amend,
> or reject.

## Context

On 2026-07-30 the factory was graded against a set of engineering principles it
already claims to hold. Three came back with the same defect, found
independently of one another:

1. **Make failure observable.** Encoded thoroughly for the plant — instrument
   fleet, ledgers, escape tracking. Absent for the factory's own actuator
   availability. Credit exhaustion on ~2026-07-27 produced a provider-scoped
   pause covering 100% of loops, indistinguishable from an outage, unalarmed for
   roughly two days (#10844).
2. **Match confidence to evidence.** Every change is gated on evidence. Nothing
   scores a judge's confidence against its own track record (#10836).
3. **Habits and review.** Every loop has a cadence, a review, and a fitness
   score (ADR-0093). The governor of those loops has none of the three.

These are not three unrelated oversights. They are one omission with three
faces: **the factory enforces its principles on what it builds and not on
itself.**

The cause is structural rather than careless. While a single operator was
present, that operator supplied the upward direction personally — noticing the
stop, holding the standard, exercising the authority unprompted. Nothing was
written down for that direction because a person was standing in it. Every rule
pointing only downward therefore carries a silent dependency on an operator who
is present and attentive, and that dependency is invisible until they are not.

Legal precedent for the shape: rule of law means the governing power is itself
bound, which is why constitutional systems entrench the amendment procedure
against the amender. A constitution binding only the governed is not a
constitution.

## Decision

**1. State the principle as canon.**

> A governance rule that binds only the plant and not the governor is not a
> rule. It is a habit the operator was silently supplying.

**2. Every ADR declares the direction it binds**, via a new required frontmatter
field:

```
- **Binds:** work | factory | both
```

- `work` — constrains what the factory builds.
- `factory` — constrains the factory's own operation: its loops, gates,
  instruments, and the authority path.
- `both`.

**3. `classify_adr_enforcement` gains a direction axis** alongside
REAL / WEAK / MISSING, so direction is queryable from the same classifier and
resolver (ADR-0100's `resolve_check` / `is_mutating`) rather than through a
parallel parse. The parsed value lives on `adr_index.ADR.binds`.

**4. `work`-only is a declaration, not a defect.** Many decisions legitimately
bind only the built artifact. What this ADR forbids is leaving the direction
*unstated*, because an unstated direction is how a downward-only rule passes for
a complete one. The `Binds: factory` declaration is also the **mechanical
backstop** for self-modification-class enumeration (#10851): it is discoverable
regardless of whether anyone remembered to classify a change as self-modifying —
enumeration catches what we thought of, the direction axis catches the rest.

## Consequences

- New `**Binds:**` field is **required at Accepted status**, enforced by
  `tests/test_adr_direction_declared.py`. The ADRs Accepted before this field
  existed are grandfathered in a shrink-only baseline in that test; each should
  gain a direction over time and leave the baseline.
- `adr_index.ADR` carries `binds: work | factory | both | unknown`; `unknown`
  (unstated) is the defect the enforcement test forbids for non-grandfathered
  ADRs.
- Pairs with the broadened self-modification class (#10851): a change to *when*
  a gate applies is self-modification just as a change to *what* it checks is;
  the `Binds: factory` axis is the backstop when the enumeration under-includes.
- **Counter-metric (per ADR-0101 / #10840):** verdict latency on governance
  changes. A direction axis + a broad self-mod class that routes every config
  tweak to an out-of-family verdict will be routed around, and a routed-around
  gate is worse than a narrow one.
