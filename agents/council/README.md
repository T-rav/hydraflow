# The Council

How HydraFlow's personas convene — **chambers** with chairs, seats, and bounded decision rights. This is the **general contract** every chamber inherits. Chambers: [design](design.md) · [architecture](arch.md). Adopted from the harvestd reference (advances #10949).

**Name of record:** *the Council, with chambers* — the PAAA house standard ruled 2026-08-25 (lineage: harvestd/HydraFlow "console" → GNAA "Board" → **Council**, GNAA decision record `council/decisions/general/0009`). "Console" read as a control surface rather than a deliberative structure; "Board" was fiduciary-adjacent. Recorded here as [ARCH-0003](decisions/arch/0003-council-rename.md). Records written under the old name keep it — see [decisions/](decisions/README.md).

## Convening

- **Read-then-embody, fresh context.** A run starts by reading the persona file and embodying it fully — verdict formats binding. Fresh context is the independence mechanism.
- **Every run emits the same evidence shape:** run timestamp · inputs read · findings/issues filed (numbers) · verdicts issued · counts verified via `gh` where counts are claimed. Composed chamber runs stamp `Mode: COMPOSED` when one substrate plays multiple seats.
- **Filing discipline:** intake lands as `hydraflow-find` issues in house format. No persona holds code, merge, spend, or policy authority — ever.

## Chambers

| Chamber | Chair | Convenes for | File |
|---|---|---|---|
| **Design** | product-manager | Specs, epics, roadmaps before they become load-bearing — does this deserve to exist as specified | [design.md](design.md) |
| **Architecture** | senior-principal | ADRs, ports/loops, standards changes; ADR-loop findings as triggers; advisory on kernel — operator ratifies | [arch.md](arch.md) |
| **General** | vp-eng | This contract's stewardship + calibration reviews (survival rates, fatigue, vote honesty); claim panels | this file + [decisions/general/](decisions/general/) |

Ops and security chambers are deliberately absent — see ARCH-0002 (deferred seats). Roster stays at span-of-control; a new persona or chamber needs a duty no existing seat or machinery holds.

**Shared rules:** seats file verdicts before the chair consolidates (no anchoring); disagreement escalates to the operator by name, never averaged; no chamber creates (adjudication only); no chamber touches merge authority, model spend, `factory_autonomy/policy.yaml`, or break-glass — those are the operator's, by standing law.

## Decision records

Every chamber keeps ADR-style decision records — one numbered file per adjudication under [decisions/](decisions/README.md). The record is the chair's **closing duty**: no committed record, no verdict. Records are immutable once merged (corrections are new records); the directory listing is the index.

## Vote-counting honesty

Same-substrate seats are **not** independent votes — this repo measured its own judge fleet at ~2 effective votes from 9 models. A composed panel counts as ~1.x effective votes; its value is dimensional (different contracts force different lenses), never statistical. Never report "panel passed" as N votes.

## Calibration (gauging the gauges)

Finding-survival-rate per persona is the needle (verified from ledgers + `gh`, never asserted). Fatigue budget: a persona whose findings stop surviving review is a miscalibrated instrument — recalibrate the contract or retire the seat. Drift: behavior diverging from the persona file is itself a finding. Cadence: conformance fails on the 6th persona-run record after the latest general calibration record (`make council-conformance`).
