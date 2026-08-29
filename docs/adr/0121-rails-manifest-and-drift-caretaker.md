# ADR-0121: The repo charter (charter.yaml) + drift caretaker — conformance as data

- **Status:** Proposed
- **Date:** 2026-08-01
- **Related:** [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker-loop pattern), [ADR-0044](0044-hydraflow-principles.md) (the audited principles), [ADR-0049](0049-trust-loop-kill-switch-convention.md) (kill-switch convention), [ADR-0082](0082-declarative-gate-contract.md) (branch-protection-drift caretaker — the shape mirrored here), [ADR-0143](0143-paaa-governance-model-and-the-decision-seam.md) (PAAA — this manifest is the Articles declaration surface; #11748 renames it to `charter.yaml` and folds these fields under a `rails:` key)
- **Addresses:** #10936 (rails manifest + drift caretaker), #11748 (renamed to `charter.yaml`, rails fields folded under `rails:`)

> **Amended 2026-08-28 by #11748.** The file this ADR designed is now
> **`charter.yaml`**, and the fields below live under a `rails:` key inside it.
> Nothing in the design changed — the tolerance rules, the writer path and the
> caretaker shape are as ruled here. What changed is the name and the nesting:
> "rails" means *template layers*, and the file the PAAA model needs (ADR-0143)
> also states purpose, articles, actors and artifacts, so it is a charter. The
> naming was ruled on 2026-08-28 and recorded in ADR-0143's Consequences;
> `build.yaml`, `standard.yaml` and keeping `rails.yaml` were all rejected there
> with reasons. Read every `rails.yaml` below as `charter.yaml`'s `rails:` block,
> `RailsManifest` as `charter.Charter` (with `charter.RailsBlock` holding these
> fields), and `RailsDriftCaretakerLoop` as `CharterDriftCaretakerLoop`. A
> pre-existing `rails.yaml` still loads for one cycle, as a rails-only charter
> carrying a non-fatal `legacy-rails-manifest` finding; no repo had one when the
> rename landed. #11748 also adds two fatal finding classes for the new
> declarations — `missing-standard` and `missing-artifact` — one tolerated class
> for an unrecognised standard id (`unknown-standard`, by the same rule Ruling 1
> applies to layer names), and one fatal `uncheckable-charter` for a declaration
> with nothing to check, so an empty charter fails loudly instead of reading as
> coverage.

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the target design and, deliberately, what is *real today* versus *v1 / unbuilt* so the build order and the enable decision are made on evidence. Accept, amend, or reject.

## Context

Stamped HydraFlow-format repos have no durable record of *which* template layers they carry or at what version. Conformance to the template is checked only when someone remembers to run `make audit` (the ADR-0044 conformance checker, `scripts/hydraflow_audit`). So rails drift silently: within one product re-baseline (2026-07) harvestd drifted to 4-of-6 kernel standards and a stale PR template, and nothing surfaced it because nothing was *watching* — there was no declared baseline to diff against.

The factory already runs two caretaker loops of exactly this shape — the ADR-drift auditor (ADR-0056) and the branch-protection-drift auditor (ADR-0082): a periodic loop that diffs live repo state against a canonical contract and files deduped `hydraflow-find` issues on divergence. What was missing was a per-repo *manifest* to diff against, and a loop to do the diffing for template layers.

## Decision

Introduce a **repo charter** — a small declarative `charter.yaml` written into each stamped/onboarded repo — and a **`charter_drift_caretaker`** loop that periodically audits each managed repo against it and files deduped drift issues. Conformance becomes tracked *data*, not an ad-hoc command.

### Ruling 1 — the declaration is small, declarative, and forward-compatible

The `rails:` block of `charter.yaml` (schema in `src/charter.py`, `charter.RailsBlock` inside `charter.Charter`) declares:

- `template_version` — the template version the repo was stamped/upgraded to;
- `layers` — the active template layers by name (`universal` kernel / `language_pack` / `domain_rails`);
- `coverage_floor` — the declared coverage floor;
- `domain_gate_scripts` — domain-specific gate scripts the repo commits to carrying.

**Tolerance rules (the crux, #10936):**

- a **missing declared layer** (declared in the charter, absent from the repo) is **drift**;
- an **undeclared extra rail** (present in the repo, not declared) is **fine** — never reported;
- an **unknown / future layer name** (e.g. the Book-3 operator-agent pack) is **tolerated and reported, never fatal**. The schema does not enumerate a closed set of legal layer names — an unrecognised name yields a non-fatal `unknown-layer` finding, never an error and never a filed issue on its own. #11748 extends the same rule to an unrecognised standard id (`unknown-standard`).

### Ruling 2 — the declaration is written by the stamping / onboarding path

The onboarding standards snapshot (`.hydraflow/standards-snapshot.json`) already carries `coverage_floor` and `tech_stack`; the charter is derived from the same snapshot (`charter_from_snapshot`) so both are written from one source. The retrofit path is the format-upgrade PR (`_open_format_upgrade_pr` in `src/dashboard_routes/_onboarding_routes.py`), which writes `charter.yaml` alongside the snapshot and commits it — this is how existing managed repos gain one. #11748 adds two more writers: the greenfield bootstrap (`src/onboarding/templating.py` renders `charter.yaml` into every materialized repo, so a new repo is governed from its first commit) and `scripts/charter_init.py`, the one-shot bootstrap for a repo that predates the file.

### Ruling 3 — the caretaker loop mirrors the existing drift loops

`CharterDriftCaretakerLoop` (`src/charter_drift_caretaker_loop.py`) follows the ADR-0029 caretaker pattern and the ADR-0049 kill-switch convention. Per tick it audits each managed repo (loads `charter.yaml`, observes live state, computes drift) and files **one deduped issue per (repo, finding class)** — fatal finding classes are `missing-layer`, `coverage-floor`, `missing-gate-script`, `missing-standard`, `missing-artifact` and `uncheckable-charter`. Dedup key: `charter_drift_caretaker:<repo>:<finding_class>`. When a finding class resolves, its open issue is closed and the key cleared so a recurrence re-files (mirrors ADR-0082's clean path). Labels: `hydraflow-find`, `hydraflow-charter-drift`. Cadence is config-driven (`charter_drift_caretaker_interval`, default 1 day).

The split matters and #11748 makes it explicit: the loop *acts*, and `charter.compute_charter_drift` *decides*, pure over the charter and one observation, reading no files and running no commands (ADR-0143 Ruling 5). Every path resolution lives in `charter_drift_caretaker_loop.observe_repo`.

## Consequences

- Repo conformance is now durable data per repo, diffed on a cadence rather than checked ad-hoc — the harvestd silent-drift class is caught.
- The loop ships per the ports-and-loops standard: first-line kill-switch (`enabled_cb`) + static config gate (`charter_drift_caretaker_loop_enabled`), an injected auditor seam for scenario testing, unit + MockWorld scenario + sandbox e2e tests, wiki term, this ADR, and a registry row across all five wiring sites.
- **Default OFF.** `charter_drift_caretaker_loop_enabled` defaults `False`: the live-observation layer (`observe_repo`) is **v1, marker-based** (`universal` ← `docs/adr/0044-*.md`; `language_pack` ← a language marker file; `domain_rails` ← `docs/standards/`), and the charter-writer retrofit is still rolling out across managed repos. The pure comparison logic (`compute_charter_drift`), schema tolerance, dedup, and loop wiring are load-bearing and tested; the concrete layer→marker mapping is a v1 assumption to be firmed up before enabling. Enable via `HYDRAFLOW_CHARTER_DRIFT_CARETAKER_LOOP_ENABLED=true` once every managed repo carries a charter and the observation mapping is confirmed. HydraFlow itself carries one from #11748, and its drift check reports clean.
- The `scripts/hydraflow_audit` charter-aware CLI mode named in #10936 is **not yet built** — the comparison currently lives in `src/charter.py` (importable by both the loop and a future CLI wrapper), and `scripts/charter_init.py` covers the one-shot bootstrap for a pre-#11748 repo. Wiring `--manifest` into the standalone audit tool is deferred to a follow-up.
