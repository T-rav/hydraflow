# ADR-0121: Rails manifest (rails.yaml) + drift caretaker — template conformance as data

- **Status:** Proposed
- **Date:** 2026-08-01
- **Related:** [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker-loop pattern), [ADR-0044](0044-hydraflow-principles.md) (the audited principles), [ADR-0049](0049-trust-loop-kill-switch-convention.md) (kill-switch convention), [ADR-0082](0082-declarative-gate-contract.md) (branch-protection-drift caretaker — the shape mirrored here)
- **Addresses:** #10936 (rails manifest + drift caretaker)

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the target design and, deliberately, what is *real today* versus *v1 / unbuilt* so the build order and the enable decision are made on evidence. Accept, amend, or reject.

## Context

Stamped HydraFlow-format repos have no durable record of *which* template layers they carry or at what version. Conformance to the template is checked only when someone remembers to run `make audit` (the ADR-0044 conformance checker, `scripts/hydraflow_audit`). So rails drift silently: within one product re-baseline (2026-07) harvestd drifted to 4-of-6 kernel standards and a stale PR template, and nothing surfaced it because nothing was *watching* — there was no declared baseline to diff against.

The factory already runs two caretaker loops of exactly this shape — the ADR-drift auditor (ADR-0056) and the branch-protection-drift auditor (ADR-0082): a periodic loop that diffs live repo state against a canonical contract and files deduped `hydraflow-find` issues on divergence. What was missing was a per-repo *manifest* to diff against, and a loop to do the diffing for template layers.

## Decision

Introduce a **rails manifest** — a small declarative `rails.yaml` written into each stamped/onboarded repo — and a **`rails_drift_caretaker`** loop that periodically audits each managed repo against its manifest and files deduped drift issues. Conformance becomes tracked *data*, not an ad-hoc command.

### Ruling 1 — the manifest is small, declarative, and forward-compatible

`rails.yaml` (schema in `src/rails_manifest.py`, `RailsManifest`) declares:

- `template_version` — the template version the repo was stamped/upgraded to;
- `layers` — the active template layers by name (`universal` kernel / `language_pack` / `domain_rails`);
- `coverage_floor` — the declared coverage floor;
- `domain_gate_scripts` — domain-specific gate scripts the repo commits to carrying.

**Tolerance rules (the crux, #10936):**

- a **missing declared layer** (declared in the manifest, absent from the repo) is **drift**;
- an **undeclared extra rail** (present in the repo, not declared) is **fine** — never reported;
- an **unknown / future layer name** (e.g. the Book-3 operator-agent pack) is **tolerated and reported, never fatal**. The schema does not enumerate a closed set of legal layer names — an unrecognised name yields a non-fatal `unknown-layer` finding, never an error and never a filed issue on its own.

### Ruling 2 — the manifest is written by the stamping / onboarding path

The onboarding standards snapshot (`.hydraflow/standards-snapshot.json`) already carries `coverage_floor` and `tech_stack`; the manifest is derived from the same snapshot (`manifest_from_snapshot`) so both are written from one source. The retrofit path is the format-upgrade PR (`_open_format_upgrade_pr`), which writes `rails.yaml` alongside the snapshot and commits it — this is how existing managed repos (harvestd first) gain a manifest.

### Ruling 3 — the caretaker loop mirrors the existing drift loops

`RailsDriftCaretakerLoop` (`src/rails_drift_caretaker_loop.py`) follows the ADR-0029 caretaker pattern and the ADR-0049 kill-switch convention. Per tick it audits each managed repo (loads `rails.yaml`, observes live state, computes drift) and files **one deduped issue per (repo, finding class)** — finding classes are `missing-layer`, `coverage-floor`, `missing-gate-script`. Dedup key: `rails_drift_caretaker:<repo>:<finding_class>`. When a finding class resolves, its open issue is closed and the key cleared so a recurrence re-files (mirrors ADR-0082's clean path). Labels: `hydraflow-find`, `hydraflow-rails-drift`. Cadence is config-driven (`rails_drift_caretaker_interval`, default 1 day).

## Consequences

- Template conformance is now durable data per repo, diffed on a cadence rather than checked ad-hoc — the harvestd silent-drift class is caught.
- The loop ships per the ports-and-loops standard: first-line kill-switch (`enabled_cb`) + static config gate (`rails_drift_caretaker_loop_enabled`), an injected auditor seam for scenario testing, unit + MockWorld scenario tests, wiki term, this ADR, and a registry row across all five wiring sites.
- **Default OFF.** `rails_drift_caretaker_loop_enabled` defaults `False`: the live-observation layer (`observe_rails`) is **v1, marker-based** (`universal` ← `docs/adr/0044-*.md`; `language_pack` ← a language marker file; `domain_rails` ← `docs/standards/`), and the manifest-writer retrofit is still rolling out across managed repos. The pure comparison logic (`compute_rails_drift`), schema tolerance, dedup, and loop wiring are load-bearing and tested; the concrete layer→marker mapping is a v1 assumption to be firmed up before enabling. Enable via `HYDRAFLOW_RAILS_DRIFT_CARETAKER_LOOP_ENABLED=true` once every managed repo carries a manifest and the observation mapping is confirmed.
- The `scripts/hydraflow_audit` manifest-aware CLI mode named in #10936 is **not yet built** — the manifest comparison currently lives in `src/rails_manifest.py` (importable by both the loop and a future CLI wrapper). Wiring `--manifest` into the standalone audit tool is deferred to a follow-up.
