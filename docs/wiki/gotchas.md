# Gotchas


## Verify imports are present and not circular before type annotations

Verify imports are present and not circular before adding type annotations. Use TYPE_CHECKING guards with `from __future__ import annotations` for forward references. Before removing imports, grep for runtime references like `isinstance` and assignments.

Example: `grep -r "SomeClass" src/` before deleting the import.

**Why:** Removing imports without checking runtime usage causes NameError crashes in production.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRS2","title":"Verify imports are present and not circular before type annotations","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954194+00:00","updated_at":"2026-05-03T04:11:32.954454+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Import ordering follows isort: stdlib, third-party, local

Import order must follow: stdlib (alphabetically, including pathlib), then third-party, then local. Run `ruff check --fix` to auto-correct ordering.

Example: `import pathlib` before `import requests` before `from . import module`.

**Why:** Misaligned imports confuse code review and cause silent import-path bugs when modules are reorganized.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRS3","title":"Import ordering follows isort: stdlib, third-party, local","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954497+00:00","updated_at":"2026-05-03T04:11:32.954499+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use `is None` and `is not None` for optional objects

Always use identity checks for None, True, False, and callable/store types: `if x is None`, `if callback is not None`. Avoid `==` comparison.

Example: `if config is None: return defaults` not `if config == None:`.

**Why:** Custom `__eq__` implementations can hide bugs; identity checks are immune and O(1).


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRS4","title":"Use `is None` and `is not None` for optional objects","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954512+00:00","updated_at":"2026-05-03T04:11:32.954513+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Protocol method signatures must match exactly

When implementing a Protocol, method signatures must exactly match the protocol definition. When updating port signatures, sync all implementations simultaneously in one task.

Example: If `Port.query(filter: str) -> list` changes, update all three implementations in one PR.

**Why:** Staggered updates create temporary inconsistencies that break protocol guarantees.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRS5","title":"Protocol method signatures must match exactly","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954524+00:00","updated_at":"2026-05-03T04:11:32.954526+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Class refactoring: enforce ≤400 lines, ≤15 public methods

Enforce size acceptance criteria during refactoring. Count carefully: non-delegated methods + delegation stubs. If a class hits these limits, extract further.

Example: 380 lines + 14 public methods is within budget; 420 lines requires extraction.

**Why:** Large classes accumulate hidden dependencies and increase change blast radius.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRS6","title":"Class refactoring: enforce ≤400 lines, ≤15 public methods","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954535+00:00","updated_at":"2026-05-03T04:11:32.954536+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve edge cases during refactoring (label ordering, removal)

When extracting or refactoring code, verify edge cases like label ordering and removal order semantics are preserved. Grep for callers to understand dependencies.

Example: If code removes labels bottom-to-top, verify the extracted method preserves this order.

**Why:** Edge case behavior often goes undocumented; breaking it silently causes production bugs.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRS7","title":"Preserve edge cases during refactoring (label ordering, removal)","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954543+00:00","updated_at":"2026-05-03T04:11:32.954546+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Delete code blocks from bottom-to-top to avoid line-number shift

When removing multiple code blocks from the same file, delete highest line numbers first. Deleting top-to-bottom shifts remaining line numbers.

Example: Delete lines 120–130 before lines 50–60 in the same file.

**Why:** Line-number shifts cause cascading edits and confusion when applying multiple deletions.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRS8","title":"Delete code blocks from bottom-to-top to avoid line-number shift","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954553+00:00","updated_at":"2026-05-03T04:11:32.954554+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Patch mock functions at definition site, not import site

Use `unittest.mock.patch('module.function')` at the definition location, not the import location. Patching import sites fails with deferred imports.

Example: `patch('hydra.core.get_config')` not `patch('module.get_config')`.

**Why:** Definition-site patching validates actual function signatures and catches keyword typos; import-site patching fails silently.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRS9","title":"Patch mock functions at definition site, not import site","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954570+00:00","updated_at":"2026-05-03T04:11:32.954572+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify file existence before planning changes

Files referenced in issues may not exist. Always verify using `git log` and `grep` before planning changes.

Example: `git log --all -- shared_prompt_prefix.py` to confirm file exists in history.

**Why:** Planning around non-existent files wastes implementation time and causes rework.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSA","title":"Verify file existence before planning changes","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954581+00:00","updated_at":"2026-05-03T04:11:32.954582+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Serialization tests must validate both directions

For serialization, test both `model_dump_json()→model_validate_json()` (format fidelity) and `save/load` cycles (integration).

Example: Test JSON round-trip AND file I/O round-trip separately.

**Why:** JSON tests catch serialization bugs; integration tests catch type coercion and persistence issues.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSB","title":"Serialization tests must validate both directions","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954589+00:00","updated_at":"2026-05-03T04:11:32.954590+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use explicit markers in tests instead of prose

Assert structured markers (IDs, status codes, field values) rather than prose content. For parser tests, include realistic multi-paragraph output containing both markers and prose.

Example: `assert 'success=True'` not `'successfully completed'`.

**Why:** Prose-dependent tests fail when output format changes; structured markers remain stable across format evolution.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSC","title":"Use explicit markers in tests instead of prose","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954598+00:00","updated_at":"2026-05-03T04:11:32.954599+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## ID generation must be consistent across all lookups

Use same ID logic everywhere files are keyed. Define prefix lengths as constants (discover=9, shape=6) and centralize extraction.

Example: `plans_dir / f'issue-{issue.id}.md'` everywhere, not mixed `issue-{id}` and `issue_{id}` patterns.

**Why:** Off-by-one slice errors silently produce NaN and cause lookup failures.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSD","title":"ID generation must be consistent across all lookups","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954604+00:00","updated_at":"2026-05-03T04:11:32.954605+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Run tests and quality checks before declaring work complete

Always run `make test` and `make quality-lite` before completion. Test failures naturally surface incomplete cleanup and hidden dependencies.

Example: Run full suite, not file-targeted subsets.

**Why:** Skipping this step lets broken imports and dead-code references ship undetected.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSE","title":"Run tests and quality checks before declaring work complete","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954610+00:00","updated_at":"2026-05-03T04:11:32.954611+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Distinguish bug exceptions from transient operational failures

Use `log_exception_with_bug_classification()` or `is_likely_bug()` to separate bugs (TypeError, AttributeError, KeyError, ValueError, IndexError) from transient errors (RuntimeError, OSError, CalledProcessError).

Example: Log bugs at ERROR level; transient at WARNING.

**Why:** Misclassifying transient errors as bugs floods Sentry with noise and masks real issues.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSF","title":"Distinguish bug exceptions from transient operational failures","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954616+00:00","updated_at":"2026-05-03T04:11:32.954617+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use logger.exception() only for genuine bugs, not transient failures

Use `logger.exception()` only when logging unexpected code bugs for Sentry. For expected transient failures, use `logger.warning(..., exc_info=True)`.

Example: Timeout → warning; AttributeError → exception.

**Why:** logger.exception() signals to Sentry that a bug occurred; misusing it on transient errors creates alert fatigue.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSG","title":"Use logger.exception() only for genuine bugs, not transient failures","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954622+00:00","updated_at":"2026-05-03T04:11:32.954623+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## HTTP errors: use reraise_on_credit_or_bug() for critical exceptions

Selectively re-raise critical exceptions (AuthenticationError, CreditExhaustedError, MemoryError) while logging transient failures. Use `reraise_on_credit_or_bug(exc)` to separate fatal from recoverable.

Example: Timeouts logged as WARNING; auth errors propagated immediately.

**Why:** Swallowing auth errors silently breaks subsequent API calls; failing fast on credit exhaustion prevents budget waste.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSH","title":"HTTP errors: use reraise_on_credit_or_bug() for critical exceptions","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954628+00:00","updated_at":"2026-05-03T04:11:32.954629+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Subprocess: catch TimeoutExpired and CalledProcessError separately

TimeoutExpired and CalledProcessError are siblings, not parent-child—both must be caught separately. Read-path methods return safe defaults; write-path methods propagate TimeoutExpired.

Example: `except (TimeoutExpired, CalledProcessError) as e:` with different handling per type.

**Why:** They share no common parent; catching one misses the other, causing silent data loss.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSJ","title":"Subprocess: catch TimeoutExpired and CalledProcessError separately","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954635+00:00","updated_at":"2026-05-03T04:11:32.954636+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Wrap per-item API calls in retry loops to isolate failures

In retry loops, wrap each item's API call in try/except so one failure doesn't abort the batch. Catch transient errors and log warnings; propagate fatal errors.

Example: Outer loop over items; inner try/except per item.

**Why:** One bad item blocking the entire batch prevents progress; isolation keeps the pipeline flowing.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSK","title":"Wrap per-item API calls in retry loops to isolate failures","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954641+00:00","updated_at":"2026-05-03T04:11:32.954642+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Background loops: classify exceptions (fatal, bug, transient)

In background loops: fatal (auth/credit) propagates, bugs (local logic) propagate, transient (per-item runtime) logged as warnings. After 5 consecutive same-type failures, publish SYSTEM_ALERT exactly once.

Example: Failed 5 GitHub API calls → SYSTEM_ALERT, not 6th.

**Why:** CircuitBreaker prevents thundering herd; clear failure classification enables targeted recovery.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSM","title":"Background loops: classify exceptions (fatal, bug, transient)","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954656+00:00","updated_at":"2026-05-03T04:11:32.954658+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Async/await: omitting await returns unawaited coroutines

Missing `await` on async methods returns unawaited coroutines that silently never execute. Pyright flags these during `make typecheck`. Store all `asyncio.create_task()` results.

Example: `await query()` not `query()`. Store task refs to prevent GC.

**Why:** Unreferenced tasks get garbage-collected silently, dropping exceptions and work.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSN","title":"Async/await: omitting await returns unawaited coroutines","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954662+00:00","updated_at":"2026-05-03T04:11:32.954663+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Config validators serve as source of truth for audit fields

Config validators (e.g., `labels_must_not_be_empty` covering all label fields) are the authoritative specification. Mismatch between validator field set and audit enumeration indicates a bug.

Example: Add regression tests verifying fields by name, not by count.

**Why:** Audit field enumeration easily drifts from validator set; field-by-field tests catch mismatches.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSP","title":"Config validators serve as source of truth for audit fields","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954668+00:00","updated_at":"2026-05-03T04:11:32.954670+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## New list[str] label fields must have optional defaults

When adding new list[str] label fields to HydraFlowConfig, always add as optional parameters with sensible defaults. Omitting causes TypeError.

Example: `labels_review_ready: list[str] = field(default_factory=list)` in ConfigFactory.

**Why:** Omitting defaults breaks callers; test that ConfigFactory.create() accepts all label fields.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSQ","title":"New list[str] label fields must have optional defaults","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954675+00:00","updated_at":"2026-05-03T04:11:32.954676+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## JSONL: append-only with idempotent writes and atomic ops

Use append-only JSONL files to accumulate state across retries. Mark entries with timestamps. Wrap all I/O in try/except OSError; use `atomic_write()` instead of `Path.write_text()`.

Example: Each line is `{"timestamp": "...", "event": ...}` ; always append.

**Why:** Append-only logs enable recovery from crashes; atomic writes prevent corruption.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSR","title":"JSONL: append-only with idempotent writes and atomic ops","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954681+00:00","updated_at":"2026-05-03T04:11:32.954682+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Schema evolution: new Pydantic fields with defaults load old state

New model fields with `field: Type = default_value` allow existing state files to load without migration. TypedDict(total=False) enables backward-compatible event payloads.

Example: Add `new_field: str = 'default'` to model; old state loads with default.

**Why:** Default values avoid schema migrations across retries, keeping state compatible.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSS","title":"Schema evolution: new Pydantic fields with defaults load old state","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954687+00:00","updated_at":"2026-05-03T04:11:32.954688+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Frozen Pydantic models: use object.__setattr__ for mutation

Critical in overrides (numeric, bool, literal) to avoid breaking setter logic. Use `object.__setattr__(model, 'field', value)` instead of direct assignment. Cross-field validation must run after numeric but before bool/literal.

Example: `object.__setattr__(config, 'retries', 5)`.

**Why:** Direct assignment on frozen models triggers validator checks before override intent is clear.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRST","title":"Frozen Pydantic models: use object.__setattr__ for mutation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954693+00:00","updated_at":"2026-05-03T04:11:32.954694+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use idempotent installation when HydraFlow manages itself

When HydraFlow manages its own repo (repo_root == HydraFlow repo), use hash-based or idempotent installation to skip if identical.

Example: Check file hash before re-running setup steps.

**Why:** Multi-execution-mode systems can trigger duplicate setup; idempotent ops prevent interference.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSV","title":"Use idempotent installation when HydraFlow manages itself","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954698+00:00","updated_at":"2026-05-03T04:11:32.954699+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve worktrees on HITL failure for post-mortem debugging

Only destroy worktrees on success in HITL workflows. On failure, preserve them to enable post-mortem inspection.

Example: `if success: cleanup_worktree()` not `finally: cleanup_worktree()`.

**Why:** Preserved worktrees enable debugging what went wrong; disk cost is acceptable trade-off.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSW","title":"Preserve worktrees on HITL failure for post-mortem debugging","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954704+00:00","updated_at":"2026-05-03T04:11:32.954705+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pass explicit self_fname parameter to avoid implicit self-exclusion

Avoid implicit heuristics like `if fname not in content` for self-exclusion. Pass explicit parameters (self_fname) to filter functions instead.

Example: `filter_by_label(files, exclude=current_file)` not implicit checks.

**Why:** Explicit parameters make logic clearer and prevent silent edge cases when names collide.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSX","title":"Pass explicit self_fname parameter to avoid implicit self-exclusion","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954710+00:00","updated_at":"2026-05-03T04:11:32.954710+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Representation consistency: document which model each helper uses

Example: ReviewRunner uses Task.id while phase_utils uses pr.issue_number for same concept. Document which representation a helper uses and scope it appropriately.

Example: Add comment `# Uses Task.id internally, not issue_number` above helper.

**Why:** Mixed usage silently produces mismatches; consolidation or explicit mapping prevents bugs.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSY","title":"Representation consistency: document which model each helper uses","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954715+00:00","updated_at":"2026-05-03T04:11:32.954716+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Stage progression: verify both ordering and progression logic

Stage progression relying on array indices (currentStage from PIPELINE_STAGES position) is fragile. New stages inserted at wrong positions silently break if only status values are verified.

Example: Test progression order AND status transitions separately.

**Why:** Index-based progression can silently break when stages are reordered.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRSZ","title":"Stage progression: verify both ordering and progression logic","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954721+00:00","updated_at":"2026-05-03T04:11:32.954722+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Skip detection triggers only for plan-stage or later

Only mark skipped when stage at index ≥3 (plan or later) has non-pending status. If issue is in triage, those phases must remain pending, not marked skipped.

Example: Discover/shape pending → issue active; plan pending + later skipped → issue skipped.

**Why:** Marking discover/shape skipped falsely signals phase completion when phases haven't run.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT0","title":"Skip detection triggers only for plan-stage or later","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954726+00:00","updated_at":"2026-05-03T04:11:32.954728+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Phase progression via label mutations is observable

Phase progression occurs via predictable label mutations (discover→shape, shape→plan). Clarity scoring gates entry: high-clarity (≥7) skip discovery; vague issues route to discovery first.

Example: Issue label history shows discover_complete → shape_in_progress → plan_in_progress.

**Why:** Deterministic label-based progression makes progression auditable in issue history.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT1","title":"Phase progression via label mutations is observable","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954732+00:00","updated_at":"2026-05-03T04:11:32.954733+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Telemetry: always expose sample_size alongside metrics

Report sample_size alongside fp_rate, recall quality, etc. Use thresholds like 10 for regressions. Empty results signal insufficient data, not successful emptiness.

Example: `{"fp_rate": 0.15, "sample_size": 2}` (noisy) vs `{"fp_rate": 0.15, "sample_size": 100}` (reliable).

**Why:** Small samples produce misleading metrics; sample_size flags sparse data.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT2","title":"Telemetry: always expose sample_size alongside metrics","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954738+00:00","updated_at":"2026-05-03T04:11:32.954739+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Aggregate telemetry by final attempt outcome, not per-attempt

Record each retry attempt separately to capture timing, but aggregate using (skill_name, issue_number) with only the final attempt's outcome for pass-rate calculations.

Example: 3 attempts → log 3 rows, count only last outcome in metrics.

**Why:** Per-attempt counting inflates failure rates with stale signals from early retries.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT3","title":"Aggregate telemetry by final attempt outcome, not per-attempt","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954744+00:00","updated_at":"2026-05-03T04:11:32.954745+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Memory filtering: check both content prefix AND metadata status

Filter evicted memories on both content prefix ('[EVICTED]') AND metadata status ('status: evicted'). Dual filtering ensures tombstones never leak into prompts.

Example: `if '[EVICTED]' not in text and memory.status != 'evicted'`.

**Why:** Single filter bugs can leak stale knowledge; dual filtering adds safety margin.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT4","title":"Memory filtering: check both content prefix AND metadata status","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954749+00:00","updated_at":"2026-05-03T04:11:32.954750+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Memory query customization: prepend context, not replace

Use `f"{prefix}, {context}"` to add context rather than replacing the original query. Narrowing queries too much degrades recall.

Example: `"memory refresh, HydraFlow PRs, " + original_query` not just `"HydraFlow PRs"`.

**Why:** Additive prefixes guide semantic search while preserving issue context for relevance.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT5","title":"Memory query customization: prepend context, not replace","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954755+00:00","updated_at":"2026-05-03T04:11:32.954756+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Enforcement ADRs: explicit tier-to-mechanism mapping

Map each enforcement tier to mechanism (pre-commit hook, linter, test, manual review) with distinct statuses for tracked items vs. those needing issues.

Example: Tier 1 → hook (enforced); Tier 2 → linter (soft); Tier 3 → audit issue (manual).

**Why:** Consequences sections must verify all proposed items have clear tracking mechanisms.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT6","title":"Enforcement ADRs: explicit tier-to-mechanism mapping","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954761+00:00","updated_at":"2026-05-03T04:11:32.954762+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Commit message validation: allow WIP and auto-generated commits

Only block commits that attempt specific format incorrectly. Allow plain commits without issue refs, WIP prefixes, merge commits, reverts, and auto-generated commits.

Example: `git commit -m "WIP"` is allowed; `git commit -m "Fix issue"` (missing 'Fixes #') is blocked.

**Why:** Blocking all non-standard commits prevents agents from making intermediate commits.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT7","title":"Commit message validation: allow WIP and auto-generated commits","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954766+00:00","updated_at":"2026-05-03T04:11:32.954767+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## New skills start with blocking=False until proven

New dynamic skills start with blocking=False to avoid breaking workflows. Graduate to blocking=True only after ≥20 runs with ≥95% success rate.

Example: Run new linter in warn-only mode; enable blocking after validation.

**Why:** New automated checks are unproven; disabling failures initially prevents build breakage.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT8","title":"New skills start with blocking=False until proven","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954772+00:00","updated_at":"2026-05-03T04:11:32.954773+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Hardcode workflow concepts in PHASE_SKILL_GUIDANCE dict

Extract workflow concepts (TDD, systematic debugging, review rigor) and hardcode them in PHASE_SKILL_GUIDANCE rather than dynamically loading from filesystem.

Example: `PHASE_SKILL_GUIDANCE = {'plan': 'use TDD...', 'review': 'systematic-debugging...'}` as Python dict, not external file.

**Why:** Hardcoding avoids dependency on superpowers installation path; keeps system self-contained.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRT9","title":"Hardcode workflow concepts in PHASE_SKILL_GUIDANCE dict","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954778+00:00","updated_at":"2026-05-03T04:11:32.954780+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Alpine Linux: use portable shell commands to consume memory

Alpine's minimal tooling excludes Python. Use portable commands like `dd if=/dev/zero bs=1M count=32 of=/dev/null` or `head -c` to test memory constraints.

Example: `dd` instead of `python -c` for memory stress tests.

**Why:** Alpine lacks interpreters; portable shell-only commands work in restricted environments.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTA","title":"Alpine Linux: use portable shell commands to consume memory","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954786+00:00","updated_at":"2026-05-03T04:11:32.954787+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Separate silent events from events with result values

Use _SILENT_WITH_RESULT frozenset checked before _SILENT_EVENTS to correctly route events (e.g., agent_end, turn_end set result but print nothing). Event handlers must have uniform signatures `(event: dict) -> str`.

Example: Check `if event_type in _SILENT_WITH_RESULT` before `_SILENT_EVENTS`.

**Why:** Events that return values but don't print need special routing; uniform signatures prevent type errors.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTB","title":"Separate silent events from events with result values","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954794+00:00","updated_at":"2026-05-03T04:11:32.954795+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Create specialized methods instead of overloading general ones

When a general method returns insufficient data for a specific use case, create separate specialized method.

Example: `list_issues_by_label` returns basic metadata; `get_issue_updated_at()` handles timestamps separately.

**Why:** Specialized methods avoid coupling unrelated concerns and make intent explicit.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTC","title":"Create specialized methods instead of overloading general ones","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954799+00:00","updated_at":"2026-05-03T04:11:32.954800+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Document top 3–5 failure risks in pre-mortem phase

Explicitly document potential failure modes before implementation. This identifies issues early and guides implementer decisions.

Example: Pre-mortem: "Risk 1: parser fails on multi-line output. Risk 2: ID collision on large batches."

**Why:** Pre-mortems catch mistakes before code review and establish concrete failure modes to guard against.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTD","title":"Document top 3–5 failure risks in pre-mortem phase","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954805+00:00","updated_at":"2026-05-03T04:11:32.954806+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Best-effort parsing: use try/except, never raise on format failure

When extracting from transcripts or external formats, wrap in try/except—never raise on parse failure. Log warnings when extraction finds zero matches on non-empty input.

Example: `try: result = parse(text) except: return []` not `except: raise`.

**Why:** External formats evolve; graceful fallback prevents crashes; warnings surface unexpected formats.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTE","title":"Best-effort parsing: use try/except, never raise on format failure","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954810+00:00","updated_at":"2026-05-03T04:11:32.954811+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## logger.error() requires format string as first argument

Logging calls must pass a format string and variable separately: `logger.error("%s", value)` not `logger.error(value)`. Passing variable directly treats it as template.

Example: `logger.error("%s", path)` not `logger.error(path)` (if path contains `%s`).

**Why:** Variables containing `%s` or `{...}` cause logging misformat or TypeError at runtime.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTF","title":"logger.error() requires format string as first argument","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954816+00:00","updated_at":"2026-05-03T04:11:32.954817+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Per-worker model overrides via HYDRAFLOW_*_MODEL env vars

Each background worker has its own `HYDRAFLOW_<NAME>_MODEL` env var (e.g., HYDRAFLOW_REPORT_ISSUE_MODEL). Defaults: report_issue=opus, sentry=sonnet, others=haiku.

Example: `export HYDRAFLOW_REPORT_ISSUE_MODEL=sonnet` to override defaults.

**Why:** Per-worker overrides enable cost/latency tuning without changing code.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTG","title":"Per-worker model overrides via HYDRAFLOW_*_MODEL env vars","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954821+00:00","updated_at":"2026-05-03T04:11:32.954822+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Hindsight recall toggle during observation window

Export `HYDRAFLOW_HINDSIGHT_RECALL_ENABLED=false` to disable reads while retaining writes. Watch metrics: wiki_entries_ingested, wiki_supersedes, reflections_bridged. Check `/api/wiki/health` for store status.

Example: Disable recall to observe effects of fresh writes without old memory interference.

**Why:** Toggling reads/writes separately enables A/B testing memory impact on production.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTH","title":"Hindsight recall toggle during observation window","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954827+00:00","updated_at":"2026-05-03T04:11:32.954828+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Self-review PRs before declaring done

After creating a PR, always self-review for gaps (missing edge cases, unhandled errors), bugs (logic errors, races), and test coverage (boundary, negative cases). Use `/superpowers:requesting-code-review` for structured review.

Example: Check diff for TODOs, error handling, test isolation before opening.

**Why:** Self-review catches obvious issues early; fresh-eyes review finds subtle ones.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTJ","title":"Self-review PRs before declaring done","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954832+00:00","updated_at":"2026-05-03T04:11:32.954833+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use explicit reasoning prompts for analysis-heavy tasks

For architecture decisions, debugging, code review: use reasoning prompts ('explain tradeoffs', 'consider edge cases'). Simple mechanical tasks (rename, format, move) don't need these.

Example: Code review → reasoning model; ruff fix → mechanical model.

**Why:** Reasoning prompts improve quality for complex analysis; mechanical tasks waste latency.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTK","title":"Use explicit reasoning prompts for analysis-heavy tasks","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954837+00:00","updated_at":"2026-05-03T04:11:32.954838+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Sentry captures real code bugs only, not transient failures

Sentry `before_send` filter drops all exceptions NOT in bug-types (TypeError, KeyError, AttributeError, ValueError, IndexError, NotImplementedError). Use `logger.warning()` for transient; `logger.error()` only for bugs.

Example: Network timeout → warning; KeyError → error.

**Why:** Sentry filtering prevents noise from transient errors; real bugs get actionable alerts.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTM","title":"Sentry captures real code bugs only, not transient failures","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954843+00:00","updated_at":"2026-05-03T04:11:32.954844+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never use git commit --no-verify or --no-hooks

Always let commit hooks run. If a hook fails, investigate and fix the underlying issue—do not bypass it.

Example: Hook fails → fix code → try commit again, not `git commit --no-verify`.

**Why:** Skipping hooks hides pre-commit quality checks and linting errors.


```json:entry
{"id":"01KQP0HK6TCK1CTRYANSJ8NRTN","title":"Never use git commit --no-verify or --no-hooks","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:11:32.954849+00:00","updated_at":"2026-05-03T04:11:32.954849+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Implement-phase: never publish work for `result.success is False`

**Pattern:** A blocking post-implementation skill (`discover-completeness`,
`scope-check`, `diff-sanity`) trips. The agent returns
`WorkerResult(success=False, commits=2)`. The implement-phase pushes the
branch and opens a PR, but the swap to `hydraflow-review` is gated on
`result.success` — so the PR sits unlabeled and the issue stays at
`hydraflow-ready`. ADR-0002's "one pipeline label per item" invariant
holds for each entity in isolation, but the *pair* drifts.

**Rule:** In `_handle_implementation_result` and `_handle_successful_push`,
gate `push_branch`, `_resolve_pr`, and `transition` on
`(result.success or is_retry)`. Fresh failed attempts never touch GitHub —
the attempt-cap mechanism retries with `prior_failure` feedback (which
also resets the worktree, discarding partial commits).

**Diagnostic signal:** open issues at `hydraflow-ready` whose
`agent/issue-N` branch has an open non-draft PR.

```json:entry
{
  "id": "implement-phase-half-state-on-skill-failure",
  "source_type": "manual",
  "topic": "implement_phase",
  "tags": ["state-machine", "ADR-0002", "skill-failure", "label-drift"],
  "rule": "Gate push_branch, _resolve_pr, and transition on (result.success or is_retry).",
  "anti_pattern": "Calling push_branch or create_pr regardless of result.success",
  "code_refs": [
    "src/implement_phase.py:_handle_implementation_result",
    "src/implement_phase.py:_handle_successful_push",
    "src/implement_phase.py:_resolve_pr"
  ],
  "fixed_in_pr": "#8713",
  "added": "2026-05-07"
}
```

## swap_pipeline_labels: same label to both is wrong for ready/review boundary

**Pattern:** `swap_pipeline_labels(issue_number, label, pr_number=pr)` applies
the SAME label to issue and PR. For most transitions this is correct (e.g.
review→fixed, both go fixed). But across the ready/review boundary it
dragged PRs back to `hydraflow-ready` when an issue was released from HITL
back to its pre-HITL origin (`pr_unsticker.py:312-322` before fix).

**Rule:** When issue and PR live at *different* pipeline stages (e.g. issue
at ready waiting for impl, PR at review awaiting human), call
`swap_pipeline_labels` twice — once for each, with the right target.

```json:entry
{
  "id": "swap-pipeline-labels-ready-review-boundary",
  "source_type": "manual",
  "topic": "label_state_machine",
  "tags": ["state-machine", "ADR-0002", "pr-unsticker", "label-drift"],
  "rule": "Across the ready/review boundary, swap issue and PR with separate calls.",
  "anti_pattern": "swap_pipeline_labels(issue, ready_label, pr_number=pr) when PR has commits",
  "code_refs": ["src/pr_unsticker.py:_resolve_or_release_back_to_hitl"],
  "fixed_in_pr": "#8715",
  "added": "2026-05-07"
}
```


## StaleIssueLoop vs StaleIssueGCLoop — distinct scopes, zero business-logic overlap

These two loops both close stale issues but target completely different populations and must not be conflated.

**`StaleIssueLoop`** (`HYDRAFLOW_STALE_ISSUE_INTERVAL`, default 24 h) owns general open issues — those without any HydraFlow lifecycle label (`planner`, `ready`, `review`, `hitl`). It fetches via `gh issue list`, filters out excluded labels, checks `updatedAt` against a configurable `staleness_days` threshold (stored in `StateTracker.get_stale_issue_settings()`), posts a farewell comment, closes the issue via `gh issue close`, and persists the closed issue number in `StateTracker` to prevent re-processing. It supports a per-setting `dry_run` mode that logs without closing.

**`StaleIssueGCLoop`** (`HYDRAFLOW_STALE_ISSUE_GC_INTERVAL`, default 1 h) owns HITL escalation issues — those carrying `hitl_label`. It uses `stale_issue_threshold_days` (default 14 days) from config (not from `StateTracker`), fetches via `PRPort.list_issues_by_label()`, and caps at 10 closes per cycle (`_MAX_CLOSE_PER_CYCLE`) to avoid GitHub rate-limiting. It uses the global `dry_run` config gate rather than a per-setting flag.

**Why both exist:** HITL escalations need a faster check cadence and a hard close-cap; general issues need per-tag exclusion logic and state-file dedup to avoid closing the same issue twice across restarts. Merging them would require either overloading `StateTracker` with HITL-specific thresholds or adding rate-limit caps to the general loop.

**Gotcha:** Adding a new lifecycle label to the pipeline requires updating the `exclude_labels` list inside `StaleIssueLoop._do_work` — otherwise newly-labelled pipeline issues will be swept as general stale issues after the configured inactivity window.


```json:entry
{"id":"01KRBX2N4QP7VW8FGH3J5YD0M7","title":"StaleIssueLoop vs StaleIssueGCLoop — distinct scopes, zero business-logic overlap","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-12T00:00:00.000000+00:00","updated_at":"2026-05-12T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## Stacked PRs: rebase onto base branch after parent merges

When a child PR is cut from a parent branch (not from `staging`/`main` directly), after the parent squash-merges you must rebase the child past the parent's tip to avoid carrying the parent's commits into the child's diff.

**Pattern:**
```bash
make rebase-onto PARENT_TIP=<sha-of-parent-branch-last-commit>
# If conflicts appear only in docs/arch/generated/:
git checkout --theirs docs/arch/generated/
make arch-regen-stage
git rebase --continue
```

`make rebase-onto` reads `config.base_branch()` (returns `staging` when `staging_enabled=True`, `main` otherwise) so you never need to hard-code the target branch.

**Why:** `git rebase --onto origin/staging <PARENT_TIP>` rewrites the child's history to start at the current tip of `staging`, excluding the parent's commits. Without `--onto`, a plain `git rebase origin/staging` re-applies the parent's commits as conflicts.

```json:entry
{"id":"STACKED-PR-REBASE-001","title":"Stacked PRs: rebase onto base branch after parent merges","topic":"git","source_type":"compiled","source_issue":41,"source_repo":null,"created_at":"2026-05-31T00:00:00+00:00","updated_at":"2026-05-31T00:00:00+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":3}
```


## `asyncio.to_thread` work must be self-bounding

`asyncio.wait_for()` / `asyncio.timeout()` only cancel the *awaiting coroutine* — they cannot cancel a running worker thread. A function dispatched via `asyncio.to_thread()` that blocks on an unbounded syscall (a blocking `fcntl.flock(LOCK_EX)`, a network-FS `open()`, an unbounded synchronous read) can pin a `ThreadPoolExecutor` worker forever even if the caller wraps the `await` in a timeout. Enough pinned workers eventually exhaust the default pool and hang every later `to_thread` call process-wide — a silent, whole-process stall with no traceback.

**Rule:** any function dispatched via `asyncio.to_thread()` must bound *itself* — it cannot rely on the caller's timeout to free the worker. For advisory file locks, use `file_util.file_lock()`, which polls a non-blocking `fcntl.flock(LOCK_EX | LOCK_NB)` against a monotonic deadline and raises `FileLockTimeout` (a `TimeoutError` / `OSError`) instead of blocking indefinitely. For subprocesses, see the equivalent `communicate()`-bounding convention documented against issue #9508.

**Why not `signal.alarm`:** `signal.alarm` only delivers to the main thread; `to_thread` work runs on worker threads, so signal-based timeouts silently never fire there.

Example: `#9600` — a wedged `fcntl.flock(LOCK_EX)` inside `EventLog._append_sync` (itself run via `asyncio.to_thread`) pinned worker after worker until the shared default `ThreadPoolExecutor` was exhausted, hanging every subsequent `to_thread` call across the whole process.

```json:entry
{"id":"TO-THREAD-SELF-BOUNDING-001","source_type":"manual","topic":"async_control","tags":["asyncio","to_thread","thread-pool-exhaustion","file_lock","ADR-0001"],"rule":"Functions dispatched via asyncio.to_thread() must bound themselves (e.g. LOCK_NB poll-loop + deadline) — asyncio.wait_for/timeout cannot cancel a running worker thread.","anti_pattern":"fcntl.flock(fd, fcntl.LOCK_EX) inside a to_thread-dispatched function, relying on the caller's asyncio.wait_for to bound it","code_refs":["src/file_util.py:file_lock"],"fixed_in_pr":"#9661","added":"2026-07-19"}
```


## docs/arch/.meta.json + changelog.md auto-resolve on merge — run `make ensure-hooks`

`docs/arch/.meta.json` and `docs/arch/generated/changelog.md` are regenerated by `arch.runner --emit` on nearly every commit (the changelog grows from `git log`; `.meta.json` carries a fresh timestamp + HEAD sha), so any two branches that both ran arch-regen conflict on them on **every** staging advance — the endless manual re-resolve. `.gitattributes` now auto-resolves both: `merge=union` for the changelog (built-in driver, honoured by GitHub's server-side merge too) and `merge=arch-meta` (keep-incoming) for the JSON.

**You must run `make ensure-hooks` once per clone** so the `arch-meta` driver is registered in git config (it is registered alongside `core.hooksPath`); otherwise `.meta.json` falls back to a normal, conflicting merge. The changelog's `merge=union` is built-in and needs no registration.

Safe because neither file is drift-checked (`arch.runner` exempts `changelog.md`; `.meta.json` is not an arch artifact) and both are re-derived deterministically on the mainline by `DiagramLoop` / `arch-regen.yml`. The OTHER `docs/arch/generated/` artifacts (`loops.md`, `ports.md`, …) are deliberately NOT auto-resolved — they are drift-checked, so a conflict there is a real content change to resolve by hand.

```json:entry
{"id":"ARCH-META-AUTOMERGE-001","source_type":"manual","topic":"git","tags":["gitattributes","merge-driver","docs/arch",".meta.json","changelog","ensure-hooks"],"rule":"docs/arch/.meta.json (merge=arch-meta, keep-incoming) and docs/arch/generated/changelog.md (merge=union) auto-resolve on merge; run `make ensure-hooks` once per clone to register the arch-meta driver.","anti_pattern":"Hand-resolving docs/arch/.meta.json + changelog.md conflicts on every staging advance","code_refs":[".gitattributes","Makefile:ensure-hooks"],"added":"2026-07-21"}
```


## Pre-push self-check — six recurring avoidable CI reds

Six patterns that pass `make quality-lite` locally but go red in CI on the first round, forcing a heal round-trip. All are already CI-guarded — the fix is to PRE-EMPT them before the first push. Check each trigger and apply the one-line fix:

1. **`fix(` commit needs a `tests/regressions/` delta (P10.6).** A commit whose subject starts with `fix(` and adds nothing under `tests/regressions/` WARNs → CI red. Add a regression test, or a `Skip-Regression:` commit trailer for a pure refactor with no behavior change. (Bit #10160, #10164.)
2. **A new subprocess call site needs a sandbox seam.** Any NEW `run_subprocess*` / `stream_claude_process` call site added in a `src/*_loop.py` (or a runner) needs a `mockworld.sandbox_main.SANDBOX_SEAMS` declaration or an injected-fake seam, or the seam-completeness ratchet goes red. (#10155 added `HealthMonitorLoop._repo_probe`'s `git ls-remote` without one.)
3. **ADR `Enforced by:` with multiple checks must be bullet lines.** The resolver only parses bullets for multiples: `**Enforced by:**` then `- pytest:a` / `- pytest:b` on their own lines — never inline `pytest:a, pytest:b`. A single inline check is fine. (#10164 used the inline form.)
4. **Extracting code to a new file relocates its `# noqa` → ratchet red.** The disturbance ratchet only shrinks; a suppression moved to a new file-signature reads as a NEW violation. Narrow the `except` to concrete types, or hoist the import to module top, so no suppression is needed. Never bump the baseline. (#10160 PLC0415, #10155 BLE001.)
5. **Moving a cited test file stales its ADR `Enforced by:` citation.** Relocating a file named in an ADR citation → ADR-conformance red. Grep the ADRs for the old path and update the citation in the same commit. (#10164 staled ADR-0085.)
6. **A test that `patch()`es a module-level import breaks when the refactor moves it.** Before relocating a symbol out of its module, grep tests/scenarios for `patch("oldmodule.symbol")` and repoint them, or the patched test errors at collection. (#10155 patched `health_monitor_loop.run_subprocess_result` after the refactor moved it out.)

**Why:** These reds are green-locally but caught only in CI, so each one costs a full heal round-trip. Pre-empting them at build time is far cheaper than a post-push fix. Mirrored in the implementer prompt's "Pre-push self-check" section (`src/agent.py:_SELF_CHECK_CHECKLIST`) and `docs/wiki/dark-factory.md` §4.8.

```json:entry
{"id":"BUILD-PREFLIGHT-SIX-CI-REDS-001","source_type":"manual","topic":"gotchas","tags":["pre-push","ci-red","P10.6","SANDBOX_SEAMS","adr-enforced-by","suppression-ratchet","adr-conformance","patch-target"],"rule":"Before the first push, pre-empt the six recurring green-locally/red-in-CI patterns: fix()→tests/regressions delta (or Skip-Regression: trailer); new run_subprocess*/stream_claude_process call site→SANDBOX_SEAMS or injected-fake seam; multi-check ADR Enforced by:→bullet lines not inline; code extraction→narrow except/hoist import instead of relocating a # noqa; moving a cited file→update its ADR Enforced by: citation; relocating a symbol→repoint tests that patch() it.","anti_pattern":"Shipping a build green-locally that hits an avoidable CI red (P10.6 WARN, seam-completeness ratchet, ADR Enforced-by inline format, suppression-disturbance ratchet, ADR-conformance stale citation, or a broken patch() target) needing a heal round-trip","code_refs":["src/agent.py:AgentRunner._SELF_CHECK_CHECKLIST","docs/wiki/dark-factory.md"],"source_issue":10169,"added":"2026-07-21"}
```

## Wall-clock time-bombs in test fixtures — dates must be now-relative

A fixture date that must sit on one side of a `now()`-relative threshold silently detonates when real time crosses it — the lane goes red on BOTH main and staging with a SYSTEMATIC off-by-one, no code change in sight. Two RC-blocking detonations in 48 hours (2026-08): `detected_at="2026-07-27"` aged past the 14-day escape-encoding threshold (#11045), and a frozen `_NOW = datetime(2026, 8, 3)` anchor aged past the judge-calibration 7-day grace window while the route read real `now()` (#11053) — the second one *looked* relative because every timestamp was `_NOW - timedelta(...)`, but the anchor itself was frozen.

**Rule:** aging-sensitive fixture timestamps derive from `datetime.now(UTC) - timedelta(...)`. A frozen anchor is safe ONLY when the code under test takes `now=` as an explicit parameter (self-consistent clock — e.g. the judge-calibration *engine* tests, vs the *route* tests that detonated). **Detection:** the systematic-both-branches-no-code-change signature distinguishes this from xdist flakes (random) and real regressions (branch-specific). **Sweep:** `make time-travel` runs the bomb-prone subset at +90 days (advisory CI lane "Time Travel"); the guard fixture lives in `tests/conftest.py` under `HYDRAFLOW_TIME_TRAVEL_DAYS`.

```json:entry
{"id":"TEST-WALLCLOCK-TIMEBOMB-001","source_type":"manual","topic":"gotchas","tags":["test-fixtures","time-bomb","now-relative","freezegun","time-travel","rc-blocking"],"rule":"Aging-sensitive fixture timestamps must be now-relative (datetime.now(UTC) - timedelta). A frozen _NOW anchor is safe only when the code under test takes now= as an explicit parameter. Sweep with make time-travel (+90d advisory lane). Diagnosis signature: systematic off-by-one on BOTH main and staging with no code change = time-bomb, not flake, not regression.","anti_pattern":"Hardcoding an absolute 'fresh' date (or freezing a _NOW anchor while the code under test calls datetime.now() internally) so the fixture silently ages past a now()-relative threshold and blocks a future RC","code_refs":["tests/conftest.py","scripts/gauge_gauntlet.py","Makefile"],"source_issue":11047,"added":"2026-08-12"}
```

## Host-dependent renders — tests must not read the operator's machine

A test whose input includes host state (`Path.home()`, installed tools, a live plugin cache) gives different verdicts on different machines — and, worse, on the SAME machine depending on import order. The criterion-6 pin test disagreed with itself three ways: CI runners (no `~/.claude/plugins/cache`) rendered agent prompts at 8,808 chars, an isolated local run imported `plugin_skill_registry` lazily *after* conftest patched `HOME=/tmp/hydraflow-test` (empty cache → 8,808, pass), but a full-suite run imported `agent` at collection time *before* the session env fixture, so the module-level `DEFAULT_CACHE_ROOT` constant captured the real home and the operator's installed skill descriptions added ~1.4k chars (10,231, fail). The failure looked exactly like an xdist flake — isolated pass, CI green, full-suite red — and got misclassified as one once before the second occurrence disproved it.

**Rules:** (1) home-derived paths are call-time functions (`default_cache_root()`), never module constants — a constant freezes whichever HOME was active at import, making behavior depend on collection order; (2) anything scored against a baseline (ADR-0087 "same input → same score") renders from checked-in fixtures only — `render_target` patches `discover_plugin_skills` with the frozen `_AUDIT_PLUGIN_SKILLS` set so the `## Available Skills` section is identical on every host. **Detection signature:** isolated-pass + CI-green + full-suite-fail *deterministically* (same failure twice in a row) = import-order-sensitive host state, not an xdist flake — measure the render in both contexts before classifying.

```json:entry
{"id":"TEST-HOST-DEPENDENT-RENDER-001","source_type":"manual","topic":"gotchas","tags":["test-fixtures","hermeticity","import-order","plugin-skills","prompt-audit","flake-triage"],"rule":"Home-derived paths must be call-time functions, not module constants (import order decides which HOME they capture). Baseline-scored renders (ADR-0087) must come from checked-in fixtures — render_target patches discover_plugin_skills with the frozen _AUDIT_PLUGIN_SKILLS set. Diagnosis signature: isolated-pass + CI-green + full-suite-fail deterministically = import-order-sensitive host state, not an xdist flake.","anti_pattern":"A module-level DEFAULT_CACHE_ROOT = Path.home()/... constant plus a render that scans the operator's live ~/.claude/plugins/cache, so prompt length (and criterion-6 membership) varied by machine and by collection order","code_refs":["src/plugin_skill_registry.py","scripts/audit_prompts.py","tests/regressions/test_audit_render_host_independent.py"],"added":"2026-08-13"}
```
