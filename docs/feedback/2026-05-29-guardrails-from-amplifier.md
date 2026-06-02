# Guardrail feedback from a downstream HydraFlow repo (amplifier)

**Date:** 2026-05-29
**Source:** the `amplifier` repo (a HydraFlow-format project), after hardening its
`main` merge gate.
**Audience:** HydraFlow standards maintainers (`docs/standards/branch_protection`,
`docs/standards/testing`, the apply-er scripts, the caretaker loops).

## Throughline

HydraFlow's release "goals" (the required gates) should be **declarative,
language-aware, and self-enforcing**, not prose that drifts from what is actually
live. Everything below comes from real friction hit while bringing one repo's
`main` gate in line with the standard.

---

## 1. Headline failure: the standard described gates that did not exist

In the downstream repo, `docs/standards/branch_protection/README.md` promised a
15-check RC gate (`Resolve RC PR`, `Browser Scenarios`, `Trust Gate`,
`Sandbox full suite`, CodeQL) and a 3-check staging baseline (`ADR gate`,
`Detect Changes`, `discover-projects`). None of them existed. The canonical
`main_ruleset.json` listed only `quality`. The live protection was classic
(not rulesets), `quality` only. A promotion merged into `main` on a single check
while the docs implied fifteen.

Nothing was bypassed. The gate enforced exactly what was implemented. The
problem was the standard's prose running far ahead of reality.

**Recommendation:** the standard's prose must never be the source of truth for
what is enforced. Generate the human-readable table *from* the canonical config,
or add a test that fails when prose and config diverge. Aspirational gates must
be marked `planned` machine-readably, never written as if active. This is the
concrete form of HydraFlow's own "don't lie about enforcement boundaries"
doctrine, applied to the standards docs themselves.

## 2. Make the goal definition declarative (flexible format)

Today a gate is implied across three places (prose + a ruleset JSON + a
workflow) with no single shape. Define each gate as one declarative record:

```toml
[[gate]]
name = "pip-audit"            # == CI job name == required-status-check context
make_target = "audit-deps"    # single entry point: local == CI == pre-commit
config = "[tool.pip-audit]"   # config lives in the language manifest (pyproject.toml)
tier = "extra"                # "core" | "extra"
required_on = ["main"]        # branches that REQUIRE it
runs_on = ["rc"]              # PR flows that TRIGGER it ("staging" | "rc" | both)
languages = ["python"]        # gate applies only when these languages are present
status = "active"             # "active" | "planned"
```

From one record you can generate the workflow trigger, the per-branch
required-context list, the docs table, and a drift check. Adding a gate becomes
adding a record, not hand-editing five files. The *format* stays fixed; the
*set* of goals grows. That is the flexibility to aim for.

## 3. Two-tier and per-branch, by default (plus a real bug)

The model that worked: **core** gate on `staging` + `rc/*`; **extras** on
`rc/* → main` only. Staging stays fast; security/e2e load onto the promotion.

`setup_branch_protection.py` **merged the contexts from every ruleset JSON and
applied that union to all branches**, so an extra meant only for `main` would
have leaked onto `staging`. The fix shipped downstream: derive each branch's
required contexts from *its own* `<branch>_ruleset.json`. Upstream the
per-branch derivation as the default behavior.

## 4. Enforce the goals as the code grows

- **Drift caretaker loop.** The Trust Fleet already runs caretaker loops. Add one
  that audits *live* branch protection against the canonical gate records and
  files an issue on divergence. The downstream repo only had a manual
  `make audit`; nothing caught the docs-vs-reality gap.
- **Path-filter footgun.** GitHub treats a path-filtered SKIPPED required check
  as "not passed," so a docs-only PR blocks forever. Standardize the **umbrella
  aggregator job** (`if: always()`, `needs:` all conditional jobs, require only
  the umbrella) so adding jobs never means editing branch protection. The
  standard already flags this as "future work" — make it the default.
- **Add-a-gate runbook.** A new required check must already exist on the base
  branch before being required, or the first PR self-blocks. Document the order:
  add gate record + workflow + config → land on `main` (gated by existing
  checks) → apply protection → verify live with `gh api`. Useful property
  confirmed downstream: for `pull_request` events GitHub runs the *head's*
  workflow, so a newly added gate self-validates on its own introducing PR even
  before it is required.

## 5. Language and project-type awareness (portability)

Guardrails must not hardcode tools. The downstream repo could not use the
standard's CodeQL: it is a **private repo without GitHub Advanced Security**, so
code scanning is unavailable (confirmed via `code-scanning/alerts` → 403 and an
empty `security_and_analysis`). We substituted **pip-audit** for the
dependency-CVE dimension. We also found vendored minified JS (`alpine`, `chart`,
`htmx`) that must be **excluded** from any scan.

**Recommendation:** a gate registry keyed by
`(language, project-type, available-capabilities)`:

| Dimension | Python | JS/TS | Cross-language |
|---|---|---|---|
| lint/format | ruff | eslint/prettier | |
| types | pyright | tsc | |
| SAST | bandit | eslint-security | CodeQL **if GHAS**, else Semgrep OSS |
| dep CVEs | pip-audit | npm audit / osv-scanner | osv-scanner |
| tests + coverage | pytest | vitest/jest | |

Plus:
- **Detect languages** from tracked manifests/extensions, excluding
  vendored/minified paths.
- **Detect capabilities/plan** (private + no GHAS → no CodeQL → fall back to
  Semgrep/pip-audit). Document which gates are runtime-enforced vs post-hoc.
- **Target the project type.** A content-only or library repo should not be
  gated by browser e2e; load-bearing services ship the full pyramid. The gate
  *contract* is identical across languages; only the tool bound to each gate
  changes.

## 6. Concrete templates worth lifting verbatim

- **`make <target>` + `[tool.*]` config + tested helper.** CI runs
  `make audit-deps`, identical to local; config in `pyproject.toml`; logic in a
  small script with unit-tested pure functions; the generated requirements
  artifact is gitignored. Good shape for any new gate.
- **pip-audit guardrail** as the canonical "dependency CVE gate" for Python
  projects without GHAS.
- **Triage allowlist in config** (`ignore-vulns = [...]`): waive a specific
  advisory by id, never an ignore-all.

## 7. What HydraFlow already got right (keep)

- "Process stays attached through merge; do not use GitHub auto-merge."
  Confirmed accurate: auto-merge was not enabled; merges were process/human
  driven.
- "Don't lie about enforcement boundaries." Exactly the principle the §1 failure
  violated. Reinforce it with the automated doc-vs-config check from §2.

---

## Net

Keep the guardrail *shape* fixed (declarative gate record → make target → config
table → per-branch required context). Let the *set* grow and vary by language
and project type. Add a drift loop so the standard cannot silently outrun
reality again.
