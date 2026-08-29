---
id: "01M15RKRY48S4039D4NPNPR964"
name: "Actors"
kind: "policy"
bounded_context: "shared-kernel"
code_anchor: "src/driver_contracts.py:WorkerRole"
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

The third layer of the PAAA governance model (ADR-0143): who or what is authorized to act on a repository, and with what delegated authority. It answers "who may change what?". The `agents/` tree — role contracts and chamber charters — *is* the Actors declaration per the 2026-08-25 house standard (#11741); a governing declaration may point at that directory but must never re-declare roles in YAML. Adjacent surfaces bound what an authorized actor may do rather than naming who it is: `WorkerRole` fixes the closed set of roles a director may request, `RepoRecord.data_class` fixes the data-governance class enforced at every model spawn, and the merge-policy autonomy classes (`act` / `ask`) fix where an agent may proceed alone and where it must ask.

## Invariants

- Actors are declared by the `agents/` directory layout; a manifest may point at it and must not restate roles — two declarations of who may act is one too many.
- A role outside the declared vocabulary cannot be invented at runtime; unknown authority values fail closed.
- Delegated authority is bounded: an actor classified `ask` cannot self-promote to `act`.
