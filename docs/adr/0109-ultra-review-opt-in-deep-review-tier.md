# ADR-0109: Opt-in "ultra" deep-review tier for the review phase

**Status:** Accepted
**Date:** 2026-07-25
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_ultra_review.py

## Context

Issue #10555 asked to expose `/code-review ultra` as an opt-in review-phase
option. The central technical question was whether that command can be invoked
programmatically from the pipeline.

**Research finding (records the answer so it is not re-litigated):** the
**cloud** `/code-review ultra` tier has **no programmatic entry point**. It is a
client-side, user-triggered, separately-billed Claude Code feature launched only
from a human's Claude Code client — agents are explicitly told they "cannot
launch it." Nothing in `src/` can invoke it, and no public/internal API surface
in this repo implies one. A repo-wide search for `ultra` in `src/` returns zero
matches.

The **reachable** equivalent is the locally-installed `code-review` plugin
command (multiple independent reviewers, then confidence-scoring that drops
low-confidence findings). HydraFlow can already dispatch that headlessly through
the exact seam `src/review_phase/_phase.py:ReviewPhase._build_post_verify_runner`
uses — `src/agent_cli.py:build_agent_command` + `src/reviewer.py:ReviewRunner`
`_execute`. The one load-bearing constraint: `build_agent_command` must be called
with `isolate_user_settings=False`, because `True` strips the `--plugin-dir`
flags, so the plugin slash-command would not resolve inside the spawn.

## Decision

Ship the ultra tier as a wrapper around the **locally-installed** `code-review`
plugin dispatched headlessly — **not** the cloud product. It is named "ultra"
after the operator-facing dial, but the ADR and wiki record that the shipped
mechanism is the local deep-review plugin, to avoid a false capability claim.

### Cost gate (three AND-ed conditions)

The fan-out is expensive, so the tier is OFF by default and, even when on, only
fires when the gate opens (`src/ultra_review.py:should_ultra_review`):

1. `config.review_ultra_enabled` is on (default `False`), **AND**
2. the issue carries the `review:ultra` label, **OR**
3. `config.review_ultra_auto_high_blast` is on (default `False`) and the diff's
   blast radius classifies as `"high"` via the existing
   `src/review_advisor.py:compute_blast_radius` / `diff_stats_from_text`.

With defaults, a full review pass issues **zero** ultra spawns — not even a
label read (the dial is checked before any I/O).

### Verdict fold

New logic is isolated in `src/ultra_review.py` (gate + command/prompt builders +
parser + dispatch helper) rather than inline in the already-large
`src/review_phase/_phase.py`. The phase adds only a thin runner adapter
(`_build_ultra_runner`, mirroring `_build_post_verify_runner`'s dual
MockWorld/production dispatch) and two fold helpers (`_maybe_fold_ultra_review`,
`_fold_ultra_findings`) invoked at the top of `_run_post_review_actions`:

- **Material findings** (confidence >= 80) flip the verdict to `REQUEST_CHANGES`
  and append to the summary, so the existing `_attempt_review_fix` hand-back and
  re-review run — no new fix machinery.
- **Sub-threshold findings** are posted as a PR comment (not dropped), verdict
  untouched.
- A **degraded** run (unparseable spawn output / transient failure) leaves the
  standard reviewer's verdict intact — fail-soft.

Credit-exhaustion / authentication / likely-bug errors from the spawn PROPAGATE
via `src/exception_classify.py:reraise_on_credit_or_bug` (docs/wiki/dark-factory
§2.2); any other runner failure fails soft to a degraded result.

Label reads go through `src/ports.py:PRPort` `get_issue_labels` (the **issue's**
labels — `PRPort` has no PR-label read method), and advisory comments through
`PRPort.post_pr_comment`.

### Test-pyramid deviation (recorded)

Coverage is unit + phase-integration (`tests/test_ultra_review.py`,
`tests/test_review_phase_ultra.py`), plus the MockWorld dispatch branch reuses
the existing `FakeLLM.script_advisor` / `pop_advisor_result` machinery under the
`ULTRA_MOCKWORLD_ROLE` key (no new fake method). No sandbox e2e tier is added:
the change is default-off, adds no docker/UI surface, and the plugin spawn is
not available inside the air-gapped sandbox. This is a deliberate deviation from
the three-layer standard, justified by the default-off cost gate and the absence
of a docker/UI surface to exercise.

## Consequences

- The pipeline gains a bounded, opt-in deep-review pass whose high-confidence
  findings actually change merge outcomes, instead of the finding being dropped.
- Misconfiguration risk (cost blow-up) is contained by the default-off dial and
  the three AND-ed trigger conditions; a test asserts zero dispatch at defaults.
- The tier is honestly named: it runs the local `code-review` plugin, not the
  cloud ultra product, which remains unreachable from `src/`.

## Related

- ADR-0045 trust architecture hardening (self-review / advisor discipline)
- `src/review_advisor.py:PostVerifyAdvisor` — the advisor pattern this tier mirrors
- `src/ultra_review.py:should_ultra_review`, `src/review_phase/_phase.py:ReviewPhase`
