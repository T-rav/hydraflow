---
id: "01M15ZFDYDYQD5FER7DDSBFADD"
name: "Charter"
kind: "value_object"
bounded_context: "shared-kernel"
code_anchor: "src/charter.py:Charter"
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

The governing declaration a HydraFlow-governed repository carries at its root, in the file named by `charter.CHARTER_FILENAME` (`charter.yaml`). It states the repository's Purpose, its Articles (adopted standards by id, an assurance class, and local articles), a pointer to where its Actors are declared, and the Artifacts it commits to carrying — the four layers of ADR-0143 — plus a `rails:` block holding the ADR-0121 template-conformance fields with their semantics unchanged. It supersedes `rails.yaml`, which loads for one cycle as a rails-only charter with a non-fatal `legacy-rails-manifest` finding. It is HydraFlow's implementation surface for the PAAA ontology, never a schema anyone outside HydraFlow is asked to conform to.

## Invariants

- `actors` is a path pointer and never a role list; a list or mapping is rejected at load, because the `agents/` tree is the Actors declaration (#11741) and a second copy rots.
- `articles.assurance` reuses the `RepoRecord.data_class` vocabulary and fails closed on anything outside it — there is no second assurance scale.
- Unknown standard ids and unknown template-layer names are tolerated and reported, never fatal (the ADR-0121 forward-compat rule).
- A charter that declares nothing checkable is fatal rather than clean: a drift check with an empty subject list reads as coverage.
- Editing `purpose` or `articles` is an ENACT reserved to the operator, not something the factory automates (ADR-0143 Ruling 6, guard 4).
