---
id: "01M15RKRY48S4039D4NPNPR963"
name: "Articles"
kind: "invariant"
bounded_context: "shared-kernel"
code_anchor: "src/rails_manifest.py:RailsManifest"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-28T00:00:00+00:00"
updated_at: "2026-08-28T00:00:00+00:00"
---

## Definition

The second layer of the PAAA governance model (ADR-0143): what must remain true of a repository — standards, architectural constraints, security and compliance rules, and local policy. It answers "what rules apply to it?". Articles are carried today by `docs/standards/`, by ADRs that declare an `**Enforced by:**` block, by `control/principles.yaml`, by `docs/standards/factory_autonomy/policy.yaml`, by `docs/standards/branch_protection/gates.toml`, and by the per-repo manifest of ADR-0121 (`RailsManifest`, renamed to `charter.yaml` by #11748) — the surface a repository uses to declare which of them apply to it. Enforcement of Articles splits three ways: the declaration declares, a decision layer classifies normalized facts as compliant / violated / exempt / grandfathered / blocking, and HydraFlow acts on the verdict.

## Invariants

- Building standards are one class of Articles, not the whole of Articles — security, compliance, architecture, and local policy are Articles too.
- The declaration is reviewable in git; a decision layer never runs tests, reads git, or writes to the repository.
- Changing an Article is an enactment reserved to the operator (ENACT, not RATIFY); nothing automates an edit to the articles of a declaration.
