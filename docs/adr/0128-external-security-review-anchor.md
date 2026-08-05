# ADR-0128: External Claude security-review Action as an out-of-band assurance anchor

- **Status:** Proposed
- **Date:** 2026-08-05
- **Related:** [ADR-0122](0122-vocabulary-scopes-for-the-three-assurance-disciplines.md) (the three assurance disciplines — this is the *safety/constraint* layer enforced by an independent controller); [ADR-0045](0045-trust-architecture-hardening.md) (trust fleet) and `src/judge_independence.py` (the `security-adjacent` blast-radius class + out-of-family independence rule this extends across the external boundary); [ADR-0044](0044-hydraflow-principles.md) (the review pipeline whose inner `security` lens this sits *outside* of); the deterministic external SAST already present — `.github/workflows/codeql.yml` (CodeQL/GHAS) + the Bandit **Security Scan** gate
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/test_external_security_review_workflow.py`
- **Binds:** factory
- **Addresses:** #10986 (external Claude review Action as an out-of-band independent security anchor — assurance, not detection)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the architecture and, deliberately, what is *active today* (the workflow, inert until a secret is provisioned) versus *owner-gated activation* (the secret and the model choice). Accept, amend, or reject.

## Context

HydraFlow is a self-modifying factory. It already has strong security *detection*: the deterministic **Security Scan** (Bandit) gate, **CodeQL/GHAS** external SAST, and a model **`security` lens** in the review phase governed by judge-independence (`src/judge_independence.py` — `security-adjacent` is a blast-radius class requiring an out-of-family independent verdict, ledgered, fail-open-but-alarmed).

What it does not have is a security constraint enforced by a controller **it does not own**. Every layer above lives *inside* the factory's boundary: the factory can, in principle, route around, degrade, edit, or learn to satisfy any of them, because it authors changes to the very code and prompts that implement them. Leveson's split — safety is an emergent *constraint* property, not a reliability *metric* — says an instrument fleet that measures reliability and infers safety is not the same thing as a constraint an independent controller enforces. #10986 asks for exactly one such constraint: an **external anchor** whose whole value is being un-editable from inside the machinery it reviews.

This is **assurance, not detection**. CodeQL already covers external SAST, so the Action adds little raw coverage. Its contribution is architectural: a second reviewer the factory cannot make pass itself.

## Decision

Add `.github/workflows/claude-security-review.yml` — the Anthropic **Claude Code Security Review** GitHub Action — as an **out-of-band, advisory-to-human** anchor, with three load-bearing invariants (pinned by `tests/test_external_security_review_workflow.py`):

1. **Advisory, never a gate.** The review step is `continue-on-error: true` and the workflow is **not** a required status check. It posts findings as inline PR comments for the human reviewer; it cannot block a merge. This is deliberate: the moment the anchor can gate the merge, the factory has an incentive (and, being a factory, the persistence) to make it pass — which pulls it *inside* the boundary it exists to sit outside of. Advisory-to-human is what keeps it external.

2. **Human-visible PRs only.** It runs on same-repo (non-fork) PRs into `staging`/`main`, excluding the factory's own governed `auto-merge` PRs (already covered by the inner lens) and dependabot. Fork PRs are excluded because the Action is **not hardened against prompt injection** and must only review trusted diffs (Anthropic's own guidance).

3. **Inert until provisioned; provisioning is a human step.** With no `ANTHROPIC_API_KEY` repository secret the job is a green no-op. Activation — adding the secret, and setting the model — is a deliberate owner action, not something a factory loop can do. That the secret and workflow live in repository settings / `.github/workflows/` (changed only through a human-visible PR to a protected branch, which is itself what this anchor reviews) is what makes the anchor *provably* outside the self-modification boundary.

### Resolving the issue's open questions

- **Q1 — model family.** The inner `security` lens defaults to Opus (`review_advisor.advisor_model`, default `"opus"`). To hold independence, the workflow reads the model from the `EXTERNAL_SECURITY_REVIEW_MODEL` repository variable, and the owner is directed to set it to a tier **different** from the inner lens. Honest caveat: the Anthropic Action is Claude-only, so full cross-vendor independence is not available here — the load-bearing independence is the **external boundary** (un-editable from inside); model-tier diversity is a best-effort second layer. (The inner lens's own family already varies under credit-failover to z.ai GLM, ADR-0119.)
- **Q2 — PR set.** All human PRs into protected branches, minus the labelled `auto-merge` factory PRs and dependabot — the defensible default of "human-visible into protected branches."
- **Q3 — verdict recording.** Findings are PR comments (human-readable) and workflow-run artifacts. They are deliberately **not** written into any factory-owned ledger: giving the factory a read/write path to the anchor's verdict would compromise the independence the anchor exists for. The assurance record is the PR comment history plus this ADR.

## Consequences

- HydraFlow gains its first security constraint enforced by a controller outside its self-modification boundary — the independent-controller / safety-layer anchor the assurance-stack argument (ADR-0122) calls for.
- No raw detection coverage is added (CodeQL already covers external SAST). If the goal is more detection, this is the wrong tool; the value is governance.
- The anchor is inert until the owner provisions `ANTHROPIC_API_KEY` (and, recommended, `EXTERNAL_SECURITY_REVIEW_MODEL`). Until then the workflow runs as a documented green no-op and never blocks CI.
- The Action is pinned to `@main` (no release tags published upstream at time of writing); pinning to a commit SHA is a hardening follow-up worth taking once a tag exists.
- Optional tiny follow-up (separate PR, prompt refinement not architecture): fold the blog's five-class checklist (SQLi, XSS, authn/authz, insecure data handling, dependency vulns) into the *inner* lens prompt if not already explicit.

## Precedent / Divergence (lineage convention)

- **Precedent:** independent security review / separation of duties; external audit.
- **Divergence:** the reviewed actor is a non-human factory that would otherwise route around or degrade any reviewer inside its own machinery. The anchor's whole value is being un-editable from inside, so it must stay advisory-to-human and out-of-family — an external-audit pattern applied to a self-modifying system.
