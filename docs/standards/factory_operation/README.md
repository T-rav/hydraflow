# HydraFlow Standard — Factory Operation (the Kernel)

HydraFlow is a factory. Designs go in. Software comes out. The point of the
factory is that this happens reliably, repeatably, and without the operator
becoming the bottleneck. This document is the kernel — the master standard
that ties the others together so a fresh repo following the HydraFlow format
inherits the entire operating model.

## The factory model

```
                ┌──────────────────────────────────────────┐
                │           DESIGNER (human)               │
                │  writes specs, sets policy, approves     │
                │  scope, evaluates the printed product    │
                └──────────────────┬───────────────────────┘
                                   │  spec / intent / labelled GitHub issue
                                   ▼
                ┌──────────────────────────────────────────┐
                │      FACTORY  (HydraFlow orchestrator)   │
                │  takes specs through the lifecycle:      │
                │    triage → discover → shape → plan →    │
                │    implement → review → HITL → merge     │
                │  governed by the standards below         │
                └──────────────────┬───────────────────────┘
                                   │  PR → integration branch → release-candidate → main
                                   ▼
                ┌──────────────────────────────────────────┐
                │             PRODUCT (software)            │
                │  shipped via the two-tier branch model    │
                │  passing the full test pyramid            │
                └──────────────────────────────────────────┘
```

The **designer** specifies what should be built. The **factory** builds it
following standards. The **product** ships when the standards are satisfied.

The operator's job is to design, not to micromanage production. Anything
the factory can do for itself, the factory should do for itself.

## The kernel standards

These standards together constitute the factory's operating contract. Every
HydraFlow-format repo gets the full set; together they describe how the
factory takes a spec from intent to production.

The table is not a reading list — it is bound to `STANDARDS_DIRS` in
[`src/onboarding/kernel_writer.py`](../../../src/onboarding/kernel_writer.py),
which is what the stamper actually copies into a new repo, by
`tests/architecture/test_factory_operation_standard_drift.py`. A standard the
table names that the stamper does not ship, or a standard the stamper ships
that the table does not name, reddens there. Both directions, because a
kernel index that is missing a kernel standard is the same defect as one that
promises a standard the child repo never receives.

<!-- standards:kernel -->
| Standard | Doc | One-line role |
|---|---|---|
| **ADR enforcement** | [`docs/standards/adr_enforcement/`](../adr_enforcement/README.md) | An Accepted ADR must bind to a check that really asserts its decision, or carry a justified exemption; the debt ratchet only falls. |
| **Branch protection** | [`docs/standards/branch_protection/`](../branch_protection/README.md) | Two-tier branch model (integration + release reference) with versioned ruleset configs and a re-applyable apply-script. |
| **Factory autonomy** | [`docs/standards/factory_autonomy/`](../factory_autonomy/README.md) | When agents act vs ask. Tractable + reversible work is factory work, not a permission gate. |
| **Factory operation** | [`docs/standards/factory_operation/`](../factory_operation/README.md) | This document. How the standards compose into one operating contract, and how the factory absorbs its own recurring patterns. |
| **Ports and loops** | [`docs/standards/ports-and-loops/`](../ports-and-loops/README.md) | Structural contract for every hexagonal port and background loop: kill-switch, fake, wiki term, ADR, registry row. |
| **Test pyramid** | [`docs/standards/testing/`](../testing/README.md) | Three layers (unit + MockWorld scenario + sandbox e2e) gate every load-bearing feature. |
<!-- /standards:kernel -->

The factory's behavior emerges from **all of them** running together.
Removing any one breaks the contract:

- Without **autonomy**: the operator becomes the bottleneck the factory
  was designed to eliminate.
- Without **the pyramid**: features pass in isolation but break in
  production, which means the operator becomes the test suite.
- Without **branch protection**: bad code reaches the release reference,
  which means the operator becomes QA.
- Without **ADR enforcement**: decisions stay prose, and the code drifts
  away from them with nothing going red.
- Without **ports and loops**: each new port or loop is a bespoke shape a
  reviewer has to catch by eye.
- Without **self-modifying maintenance** (this document,
  §"Self-modifying maintenance mode"): every recurring failure mode is
  solved manually, which means the operator becomes the fix-up bot.

### Standards that stay here

`docs/standards/` also holds standards that are deliberately **not** stamped
into child repos. Each is a rule about instruments this repo builds and other
repos do not have; shipping the prose without the machinery would hand a new
repo a rule with no gate behind it — the exact shape both of them exist to
prevent. The same test binds this table to the complement of `STANDARDS_DIRS`,
so a new standard directory cannot appear in neither table.

<!-- standards:local -->
| Standard | Doc | Why it stays here |
|---|---|---|
| **Parametrised guards** | [`docs/standards/parametrised_guards/`](../parametrised_guards/README.md) | Its gate is a registry of *this* repo's architecture guards (`tests/architecture/guard_enumeration_registry.py`). A repo with no such guards inherits an empty rule. |
| **Vitals vs conformance** | [`docs/standards/vitals_conformance/`](../vitals_conformance/README.md) | Its enforcement is a classification of this repo's own checks plus an egress-blocked CI lane. Stamping the prose without the lane ships a claim nothing answers. |
<!-- /standards:local -->

Moving one of these into the kernel means shipping its enforcement too:
add it to `STANDARDS_DIRS`, move its row to the kernel table, and the test
above stays green. Moving only the row does not.

## Self-modifying maintenance mode

This section describes the **inner learning loop** — the factory observing its
own runtime patterns and absorbing them. The **outer learning loop** — operator
+ Claude doing capability work manually, then feeding the pattern back into the
factory via methodology docs + issues — is documented separately at
[`docs/methodology/learning-cycle-manual-to-factory.md`](../../methodology/learning-cycle-manual-to-factory.md).
Both loops produce the same shape of output (the factory grows new lobes); only
the inputs differ. Inner observes; outer creates.

### Inner cycle (this section)

The factory does not stay static. As it operates, patterns surface that the
factory itself should automate:

1. **Recurring CI failure modes** that follow a fixed recipe (stale
   auto-regenerated artifacts → run regen + push; lint formatting →
   run lint-fix + push; PR base mismatch → retarget) become caretaker
   loops.

2. **Recurring documentation gaps** (e.g. tests authored against
   non-existent state shapes; placeholders that ship under sNN file
   names but assert nothing meaningful) become principles-audit checks.

3. **Recurring design oversights** (a feature that shipped without one
   of the test-pyramid layers; a PR that bypassed the two-tier branch
   model) become explicit anti-patterns in the relevant standard, plus
   an audit rule.

The flow:

```
   recurring manual fix  ─────────→  hydraflow-find issue  ─────────→
       (3+ instances)                  (filed by the agent that
                                        recognized the pattern)

   ─────────→  caretaker loop spec  ─────────→  loop ships, follows
                  (designer review)                test pyramid

   ─────────→  loop runs in production, factory autonomy expands
```

Each iteration of this flow shrinks the operator's manual surface and
expands the factory's autonomous surface. That is what "self-modifying"
means: the kernel grows new lobes as it learns.

### The discipline

- After **three or more** instances of the same kind of manual fix, the
  agent that recognizes the pattern files a `hydraflow-find` issue. Do
  not silently keep applying the fix; that hides the signal.
- The find-issue includes: what the manual fix is, where it has been
  applied (PR / commit references), the proposed automation, and an
  estimate of cost vs benefit.
- Caretaker-loop specs go through the standard
  brainstorming → spec → plan → TDD execute flow. Self-modification
  does not bypass discipline; it follows it.

## How a fresh HydraFlow-format repo bootstraps

1. Copy `docs/standards/` into the new repo (or fork from the canonical
   HydraFlow template).
2. Copy `CLAUDE.md` Quick Rules + Knowledge Lookup index sections, replacing
   project-specific text but keeping the structure.
3. Run `python scripts/setup_branch_protection.py --apply` to encode the
   two-tier ruleset into GitHub.
4. Set `HYDRAFLOW_STAGING_ENABLED=true` in `.env` (gitignored).
5. Boot the orchestrator. The factory starts running.

The standards are the factory's tooling. Once they're in the repo, the
factory's behavior is reproducible.

## What is NOT in the kernel

The kernel is the operating contract. It does **not** specify:

- The product. Each repo's spec describes what HydraFlow should build for
  that project. The kernel doesn't care; it just runs the factory.
- The model. Which LLM, which tool, which prompt is a configuration
  concern, not a kernel concern.
- The cadence. RC promotion every 4 hours vs every hour vs once a day is
  a configuration knob (`rc_cadence_hours`).

Kernel standards are about **process**: how work moves through the
factory, who has authority over what class of decision, and how the
factory learns. Product, model, and cadence are above (designer-set) or
beside (config) the kernel.

## Discoverability

This kernel doc lives in one place by name and is referenced from:

- `CLAUDE.md` Knowledge Lookup index (the "Cross-cutting standards" row)
- Each of the sub-standards' "Discoverability" section
- `docs/wiki/dark-factory.md` (the operating-contract wiki entry)

A future audit (extension of `principles_audit_loop`) should check that
every HydraFlow-format repo has all of `STANDARDS_DIRS` present and the
kernel references resolve.

## Enforced by

The gates that hold this document to its artifact. This list is the same
set as `enforced_by` in [`standard.yaml`](standard.yaml); editing either
side alone reddens `tests/architecture/test_standards_registry.py`, which
also checks that every cited path is still **collected by pytest** — a
gate that exists but never runs is a citation to nothing.

<!-- standard:enforced-by -->
- `tests/architecture/test_factory_operation_standard_drift.py`
<!-- /standard:enforced-by -->
