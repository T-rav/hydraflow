# ADR-0082 — Declarative Gate Contract for Branch Protection

**Status:** Proposed
**Date:** 2026-05-29

## Context

Downstream feedback from the `amplifier` repo (`docs/feedback/2026-05-29-guardrails-from-amplifier.md`) found that HydraFlow's release gates drift because they are described in prose that runs ahead of what is actually enforced. The throughline of that feedback: gates should be declarative, language-aware, and self-enforcing, not prose maintained by hand alongside a ruleset JSON and a workflow.

Ground-truthing the feedback against this repo surfaced a live instance of the same failure. The `ADR gate` context was required on both `main` and `staging` rulesets, but its producing workflow (`adr-touchpoints.yml`) was deliberately deleted (commit `29f26763`) when ADR enforcement moved to the `adr_touchpoint_auditor` caretaker loop (ADR-0056). The required-status-check context was never removed from the canonical rulesets, so the standard asserted a gate that no longer exists. A required check that no workflow produces blocks PRs or silently never runs. This is the concrete form of HydraFlow's "do not lie about enforcement boundaries" doctrine, violated in the home repo.

Before this ADR, a gate was implied across three uncoordinated places: prose in `README.md`, the ruleset JSON, and a CI workflow. There was no single shape to add, audit, or test, and no language or capability awareness (CodeQL was hardcoded, so a repo without GitHub Advanced Security could not adopt the standard cleanly).

## Decision

A single hand-authored contract, `docs/standards/branch_protection/gates.toml`, is the source of truth for branch-protection gates. Each `[[gate]]` record is one (dimension, binding) pair carrying its check context name, the `tier` (core or extra), the branches it is `required_on`, the PR flows it `runs_on`, its `languages` and `requires_capability`, its `status` (active or planned), and the `(workflow, job)` that produces it. Per-branch `[branch.*]` tables carry the non-status-check ruleset rules (merge methods, code-quality, code-scanning).

From this contract:

1. `scripts/gen_gates.py` (run as `python -m scripts.gen_gates`) generates the per-branch ruleset JSON (`main_ruleset.json`, `staging_ruleset.json`) and the gate table inside a generated block in `README.md`. `make gen-gates` writes the artifacts; `make gen-gates-check` fails on drift.
2. `scripts/gates/validate.py` fails when any active gate's `(workflow, job)` producer is absent. This forbids the orphan-required-check class of drift, the exact failure that left `ADR gate` required with no producer.
3. The committed ruleset JSON and README table are generated artifacts; a standalone `gates-drift.yml` workflow runs `gen-gates --check` on every PR so prose, JSON, and CI cannot silently diverge.

Slice 1 (this ADR's initial scope) reproduces the prior enforced state exactly, with one correction: the stale `ADR gate` context is removed (main goes from 15 to 14 required checks, staging from 3 to 2), because ADR enforcement is the `adr_touchpoint_auditor` loop now, not a CI gate. The same change fixes a false-negative in `setup_branch_protection.py --audit`, which failed to paginate the branch listing and so reported `staging` as missing on repos with more than one page of branches.

Subsequent slices, sequenced in the implementing plan, extend the contract without changing its shape: capability and language binding (CodeQL if GHAS is present, else Semgrep or pip-audit, with a hard failure rather than a silent skip when a required dimension has no available binding); `hydraflow_init` consuming the contract to bootstrap a new repo's gates from its detected languages and capabilities; a triage/review check that proposes activating a gate when a change introduces the surface it protects, recorded back into the contract as a reviewed PR or label rather than a direct GitHub mutation; and a caretaker loop that reconciles live branch protection against the merged contract. Every change to what is enforced originates from a merged commit, so git history is the audit trail.

## Consequences

- Adding or changing a gate is editing one record, not hand-syncing prose, JSON, and a workflow.
- The standard's prose cannot outrun what is enforced: a stale artifact or an orphan required context fails CI.
- The guardrail shape is fixed while the set of gates can grow and vary by language, project type, and capability, which is what lets one standard fit repos that cannot run CodeQL or do not need browser e2e.
- The staging baseline is two always-on checks; ADR enforcement stays with the `adr_touchpoint_auditor` loop (ADR-0056).
- This extends the Enforcement section of ADR-0042; it does not supersede it.

## Alternatives considered

- **Named profiles only** (a fixed set of curated gate bundles per project type). Rejected: adding or varying a gate still means hand-editing bundles, which reintroduces the drift this ADR removes.
- **Fully agentic enforcement via loops and triage/review, with no version-controlled contract.** Rejected: it recreates the §1 failure. "What this repo enforces" would live only in GitHub's live ruleset plus whatever an agent last decided, with nothing to diff against or test. A concrete, reviewed, testable statement of the enforced state is the property that keeps the standard honest. Judgment about *when* to grow the gate set belongs in triage/review; the *record* of the decision belongs in the contract.
- **Keep the hand-maintained ruleset JSON (status quo).** Rejected: it is exactly what drifted.

## Related

- [ADR-0042](0042-two-tier-branch-release-promotion.md) — two-tier branch model; this ADR extends its Enforcement section
- [ADR-0056](0056-adr-touchpoint-gate-to-caretaker-loop.md) — ADR enforcement moved from a CI gate to the `adr_touchpoint_auditor` loop
- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern (the drift-reconciliation loop)
- `docs/standards/branch_protection/gates.toml` — the contract
- `scripts/gates/` — loader, resolver, docs-table renderer, validator
- `scripts/gen_gates.py` — generator CLI; `make gen-gates` / `make gen-gates-check`
- `.github/workflows/gates-drift.yml` — drift check on every PR
- `src/branch_protection_auditor_loop.py:BranchProtectionAuditorLoop` — the caretaker loop that audits live protection against the contract and files an issue on drift
- `src/branch_protection_audit.py:audit_repo` — shared live-vs-canonical audit core (used by the loop and the `setup_branch_protection.py` CLI)
- `scripts/gates/bootstrap.py` — init-time gate bootstrap (detect profile, resolve, plan section)
