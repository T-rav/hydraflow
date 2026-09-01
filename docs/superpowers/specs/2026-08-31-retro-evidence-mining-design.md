# Retro evidence mining — trace-grounded GATE / POLICY / BUGFIX findings

**Status:** Design · **Date:** 2026-08-31 · **Loop:** `retrospective` (extends ADR-0074)
**Pattern:** Caretaker loop (ADR-0029) · Kill-switch (ADR-0049) · Class-issue filing (#11292)
**New ADR:** 0144 (verify the number is unclaimed by an open PR before writing — #10243 collision class)

## Problem

`RetrospectiveCollector._detect_patterns` is the factory's only automated
retro. It reads `RetrospectiveEntry` — thirteen fields of PR metadata (plan
accuracy, quality-fix rounds, review verdict, CI rounds, duration) — and emits
four hardcoded threshold branches, capped at one per run. Their entire output
vocabulary is:

> "Consider strengthening the implementation prompt to emphasize running `make quality`."
> "Consider improving the planner prompt to better analyze dependencies."
> "The implementation prompt likely needs strengthening to produce higher-quality first drafts."
> "The planner should be made aware that this file commonly needs changes."

None of those name a file, a command, an error, or a guard. That is not a
prompt-tuning defect — **the loop has no evidence channel that could produce
anything sharper.** No field on `RetrospectiveEntry` can carry a repro.

Meanwhile the evidence has been on disk the whole time. ADR-0044 P8.6 says so
in its own remediation text — *"without traces, session retros have nothing to
mine"* — and `src/trace_collector.py` has been writing exactly those traces per
phase per run, keyed by issue number, unread by the retro.

## Existing substrate (build on, do not rebuild)

| Artifact | Path | Carries |
|---|---|---|
| `SubprocessTrace` | `<data_root>/traces/<issue>/<phase>/run-<N>/subprocess-<i>.json` | `tool_counts`, `tool_calls` (name + `input_summary` + `succeeded`), `skill_results`, `tokens`, `crashed`, `error`, `turn_count`, `inference_count`, `backend`. **`tool_errors` and `ToolCallSpan.error` are declared but never populated — see §0.** |
| Phase transcripts | `<log_dir>/{issue,plan-issue,triage-issue,hitl-issue,research-issue,discover-,shape-}<n>.txt` | Raw agent output, written by `BaseRunner._save_transcript` |
| Class-issue filing | `src/find_class_key.py:file_or_fold` | Class-key marker, site folding, legacy-issue marker stamping, 0-sentinel contract |
| Memory suggestion | `phase_utils.file_memory_suggestion` | The HITL-signed path |
| LLM spawn | `runner_utils.run_lightweight_agent` | Prompt-gate handling, credit signals |

Nothing in this spec introduces a new storage format, a new queue, or a new
loop. It adds a read path over data that already exists and a validated
emission contract.

## Design

### §0 — Prerequisite: make the trace honest (ships as its own PR, first)

**The trace does not currently record tool errors.** Verified by driving the
real collector with a failing `Bash` tool_result:

```
tool_errors      : {}
span.succeeded   : True   <- the tool FAILED
span.error       : None
```

Three separate causes, one per backend:

- **Claude** (`_handle_user_tool_result`) flips the span to `succeeded=True` on *any* `tool_result`, never reading `block["is_error"]`.
- **Pi** (`_handle_pi_tool_end`) does the same, ignoring any error field on the event.
- **Codex** (`_handle_codex_item`) handles `function_call` but has **no completion handler at all**, so its spans stay `succeeded=False` with `duration_ms=0` forever.

So `ToolCallSpan.succeeded` means three different things depending on backend,
`ToolCallSpan.error` is universally `None`, and `TraceToolProfile.tool_errors`
only ever receives the literal key `"__stream__"` from `_handle_error` — which
also drops the message text to `logger.debug` rather than into the trace. It is
never keyed by tool name.

Why nobody noticed: every test builds `TraceToolProfile(tool_errors=...)` by
hand (`tests/test_trace_models.py:55` asserts `tool_errors["Bash"] == 1` on a
literal it constructed itself). The field is pinned at the **model** level and
never at the **collector** level, so deleting the collector's error handling
entirely would keep the suite green. Spelling, not behaviour.

Downstream, `src/trace_rollup.py:139-189` aggregates a per-tool error
breakdown across traces. That breakdown has been structurally empty for its
whole life.

**PR 1 scope — Claude only, deliberately.** Only Claude's error shape is
authoritative in-repo: `is_error` on the `tool_result` block, corroborated by
`src/stream_parser.py:582` and by `src/director_sandbox.py:188` ("`is_error` is
authoritative and `subtype` must never gate"). For Pi, `_parse_pi_tool_end`
reads only `result`; for Codex, `_parse_codex_item` reads only `type`/`text`.
Neither the code nor `docs/` records an error field for those backends, and
there is no captured fixture — `tests/fixtures/stream_json/` holds
`claude_implement_sample.jsonl` and nothing else.

Guessing `isError` / `status` for the other two would ship a sentinel that
silently never matches, which is the same class of defect as the one being
fixed. So PR 1:

1. Populates `tool_errors[tool_name]`, `succeeded=False`, and
   `error=<truncated result text>` on the **Claude** path.
2. Carries `_handle_error`'s message into the trace instead of dropping it to
   `logger.debug`.
3. Leaves Pi and Codex untouched, with an explicit test asserting they are
   *currently* unpopulated, so the gap is visible rather than assumed-fixed.

Pi and Codex error capture is a follow-up blocked on capturing one real stream
fixture per backend. Filed rather than faked.

Behavioural regression pin in `tests/regressions/`, driving
`TraceCollector.record`, not constructing `TraceToolProfile`.

Every signal family in §2 depends on this landing first.

### §1 — `src/retro_evidence.py` (pure)

```python
def gather(config: HydraFlowConfig, issue_number: int) -> RetroEvidence
```

Reads that issue's trace JSONs and phase transcripts off disk into a
`RetroEvidence` bundle. No network, no subprocess, no writes — extractors stay
pure so they unit-test without a fixture factory and can never be the reason a
retro tick fails. Missing traces or transcripts yield an empty bundle, not an
error: a repo that predates trace collection degrades to zero findings.

Orchestration: `_handle_retro_patterns` already loads the last
`retrospective_window` `RetrospectiveEntry` rows; it maps those to their
`issue_number` and calls `gather` once per issue. No new source of issue
identity is introduced.

### §2 — `src/retro_signals.py` (pure, deterministic)

```python
def extract(bundles: Sequence[RetroEvidence]) -> list[RetroSignal]
```

Quantifies what actually went wrong, across the `retrospective_window` of
issues. Each `RetroSignal` carries an `id`, a normalized `signature`, a
`count`, the issues it spans, and `evidence_refs` (trace path + transcript
offset). Extracted signal families:

- **Tool-error clusters** — `ToolCallSpan.error` (post-§0) over spans with `succeeded=False`, keyed by normalized error text. `tools.tool_errors` gives the cheap per-tool count for cross-checking the cluster totals.
- **Crash signatures** — `crashed=True` subprocesses grouped by phase + `SubprocessTrace.error`.
- **Skill failures** — `skill_results` where `passed=False`. Note `SkillResultRecord` carries **no error text** (`skill_name`, `passed`, `attempts`, `duration_seconds`, `blocking` only), so a skill-failure signal can ground a `GATE` or `POLICY` finding but **never a `BUGFIX`** — there is no excerpt for the §4 substring check to resolve against.
- **Tool thrash** — the same `tool_name` + identical `input_summary` N+ times in one run (the edit-retry loop shape). Buildable today; `input_summary` is populated.
- **Command failures in transcripts** — normalized via the existing `log_ingest_loop` signature normalizer (timestamps, UUIDs, `#N`, paths, hex, numbers → placeholders). Reuse it by extracting the function to a shared module rather than copying — a second copy drifts.

**Signals must key on `error is not None`, never on `ToolCallSpan.succeeded`.**
This holds *after* §0, not just before it. §0 fixes the Claude path only, so a
Codex span still ends `succeeded=False, error=None` — never closed, because
Codex has no completion handler. A signal reading `succeeded is False` would
therefore score every Codex tool call as a failure, while `error is not None`
correctly reads it as unknown. Verified post-fix:

```
codex span: succeeded=False  error=None
```

`succeeded` becomes safe to read only once the Pi/Codex follow-up lands.

Signals are the LLM's *only* permitted grounding. A finding that cites no
signal id is rejected in §4.

### §3 — `src/retro_finder.py` (the LLM stage)

Sends the structured signals plus **bounded transcript excerpts anchored to
those signals** (not whole transcripts — cost, and whole-transcript context is
what produces mush). Asks for strict JSON: a list of findings, each with
`kind ∈ {gate, policy, bugfix}` and that kind's required anchor fields.

Spawns via `run_lightweight_agent` on new config keys mirroring the
`transcript_summary_*` family (`retro_finder_model` / `_tool` / `_provider` /
`_timeout`). **Calls `reraise_on_credit_or_bug` in its broad except** — this is
a subprocess-spawning path, and swallowing `CreditExhaustedError` here would
burn retro ticks against an exhausted account (dark-factory §2.2).

Model unavailable, timed out, gate-blocked, or emitting unparseable JSON →
zero findings, one warning, tick still succeeds. The retro is best-effort by
construction; it must never block the merge path or red a loop.

### §4 — `src/retro_findings.py` — the validator IS the gate

`RetroFinding` is a discriminated union on `kind`. The anchor fields are
required and non-empty, so **a finding without a concrete artifact is not a
low-quality finding — it is unconstructable.**

| kind | required anchors | resolution check |
|---|---|---|
| `GATE` | `guard_path`, `signal_id`, `observed` | `guard_path` must sit under `tests/architecture/`, `.claude/hooks/`, or `.github/workflows/`; `signal_id` must name a signal from §2; `str(signal.count) in observed` — the finding must literally restate the count it claims to have observed, which a prose-only `observed` cannot |
| `BUGFIX` | `repro_command`, `repro_file`, `error_excerpt`, `signal_id` | `repro_file` must exist in the tree; **`error_excerpt` must be a literal substring of the cited evidence** |
| `POLICY` | `doc_path`, `rule_text`, `signal_id` | `doc_path` must exist — POLICY amends an existing doc (`CLAUDE.md`, `docs/standards/*`, `docs/wiki/*`); proposing a brand-new doc is out of scope for the automated path |

`validate(findings, evidence, signals, repo_root) -> (kept, dropped)`

Every check is deterministic and filesystem-local, so the validator is fully
unit-testable with no model in the loop. A hallucinated path or an invented
error string fails resolution and is **dropped and counted**, never filed. The
drop count is returned in the loop result and published as an event, so a
model that starts confabulating shows up as a rising drop rate rather than as
issue spam.

### §5 — Emission

- `GATE` / `BUGFIX` → `find_class_key.file_or_fold(prs, source="retrospective", needle=<signal.signature>, site=<anchor>, labels=["hydraflow-find"])`. These findings are pattern-shaped by construction (a signal spans N issues), so they file **one class issue** and later siblings fold into it — never one issue per site (#11292).
- `POLICY` → `file_memory_suggestion` for HITL. Policy text is signed by a human, not merged by a bot: this preserves the harnessed-not-autonomous property (`docs/wiki/patterns.md` "Why memory/observation is harnessed").
- Per-tick cap from `retro_findings_max_per_tick` (default 3) so one noisy window cannot flood the board.

`file_or_fold` needs a `PRPort` with `list_issues_by_label` / `update_issue_body` /
`create_issue` / `post_comment` — all four present on `src/ports.py`.
`RetrospectiveLoop._prs` is typed `PRPort | None` but is wired non-`None` at
`src/service_registry.py:1880`; emission still guards on `None` and no-ops
rather than raising, so a partially-wired test harness degrades quietly.

### §6 — Retirements and a fix

- **Delete** all four `_detect_patterns` threshold branches and the prose bodies in `_file_improvement_issue`. They are the output being objected to, and `quality_fix` / `plan_accuracy` are strictly better served by trace signals.
- **Delete** the now-unreachable `filed_patterns` `DedupStore` — dedup moves to the class-key marker, which is durable in the issue body rather than in local JSON.
- **Fix** `RetrospectiveLoop._handle_retro_patterns`, which today returns a hardcoded `{"patterns_filed": 0}` regardless of what was filed. The loop's own telemetry has always reported zero. Return real counts (`filed`, `folded`, `dropped`).

This is a deletion-bearing change, so it ships with **full `make quality`**, not
a file-targeted subset (the #8460 over-prune class).

## Config

| Key | Default | Meaning |
|---|---|---|
| `retro_finder_enabled` | `true` | Master switch for the §3 LLM stage; off → deterministic signals recorded, no findings filed |
| `retro_finder_model` / `_tool` / `_provider` / `_timeout` | mirrors `transcript_summary_*` | Backend for the finder spawn |
| `retro_findings_max_per_tick` | `3` | Emission cap |
| `retro_evidence_max_chars` | `40_000` | Excerpt budget sent to the model |

Existing `retrospective` kill-switch (ADR-0049) and
`retrospective_loop_enabled` continue to gate the whole loop above all of this.

## Testing — full pyramid

**PR 1 (§0)**
- `tests/test_trace_collector_tool_errors.py` — Claude: a failing `tool_result` yields `succeeded=False`, non-`None` `error`, `tool_errors[tool_name] == 1`; a succeeding one leaves `tool_errors` empty. Plus an explicit **gap test** pinning Pi/Codex as unpopulated, so the follow-up has a failing-by-design target to flip.
- `tests/regressions/` — behavioural pin driving `TraceCollector.record`, not constructing `TraceToolProfile`.

**Unit (PR 2)**
- `tests/test_retro_evidence.py` — gather over a seeded trace tree; missing dirs → empty bundle, no raise.
- `tests/test_retro_signals.py` — each signal family; signature normalization stability.
- `tests/test_retro_findings.py` — **one rejection test per required anchor per kind**, parametrised over the field set by reference so a new anchor field cannot be added without a guard (`docs/standards/parametrised_guards/`). Plus: nonexistent `repro_file` dropped; `error_excerpt` absent from evidence dropped.
- `tests/test_retro_finder.py` — mocked `run_lightweight_agent`: malformed JSON → zero findings; timeout → zero findings; `CreditExhaustedError` **re-raised, not swallowed**.

**MockWorld scenario** — sibling of `tests/sandbox_scenarios/scenarios/s18_retrospective_empty_queue.py`: seed a trace tree with a repeated tool error, run the loop, assert exactly one `hydraflow-find` class issue and that a second tick folds rather than refiles.

**Sandbox e2e** — filing path end-to-end through FakeGitHub, asserting the class-key marker lands in the body.

**Regression** — `tests/regressions/` pin for the `patterns_filed: 0` telemetry lie.

## Consequences

- The retro gains an evidence channel; its output becomes anchored artifacts a builder can act on without re-deriving context.
- The vagueness fix is structural (unconstructable findings), not a prompt asking for specificity — so it cannot regress by prompt drift.
- New cost: one lightweight model spawn per retro tick that has signals. Bounded by the excerpt budget and the per-tick cap; degrades to zero findings rather than to failure when credits are out.
- Trace-less history yields nothing. Findings only cover issues processed after trace collection was active.
- §0 makes `src/trace_rollup.py`'s per-tool error breakdown non-empty for the first time. Anything already rendering that rollup (dashboard, vitals) will start showing real numbers where it showed none — a visible change nobody asked for, worth calling out in the PR body.

## Sequencing

**PR 1 — §0 only.** Trace-collector error capture across three backends, with
its own regression pin. Independently valuable: it fixes a rollup that has
reported empty forever. Merges before PR 2 starts.

**PR 2 — §1–§6.** Evidence mining, signals, finder, validator, emission,
retirements. Depends on PR 1's data.

## Open items for implementation

1. Confirm ADR number 0144 is unclaimed by an open PR before writing the ADR (checked 2026-08-31: no open PR titles it; re-check at write time).
2. Extract the `log_ingest_loop` signature normalizer to a shared module (do not copy).
3. File a follow-up for Pi/Codex tool-error capture, blocked on capturing one real stream fixture per backend into `tests/fixtures/stream_json/`.
4. Register new modules in `docs/arch/functional_areas.yml`; run `make arch-regen`.
