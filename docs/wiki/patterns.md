# Patterns


## Schema evolution with optional fields and type narrowing

Preserve backward compatibility through optional fields with sensible defaults and type narrowing on bare strings (safe if values already conform). Use StrEnum for auto-conversion. Pydantic v2 auto-coerces dicts from state.json; verify all call sites before narrowing union types. Establish single source of truth via canonical constants (e.g., `ALL_LIFECYCLE_LABEL_FIELDS`). Use metadata tags for categorization instead of enum variants. Make new fields optional with `.get()` defaults on read; no migration needed.

**Why:** Prevents deserialization failures and subtle logic bugs when callers expect different types than you assume.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJW6","title":"Schema evolution with optional fields and type narrowing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404820+00:00","updated_at":"2026-05-03T03:56:15.404843+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify call sites before refactoring function signatures

Before changing function signatures, grep the codebase to find all call sites and confirm scope. For public functions, use `git grep` to verify zero remaining matches after refactoring. When return types change (e.g., `str | None` → `dict | None`), update all callers atomically in a single commit. Example: Before renaming a parameter or adding required arguments, run `git grep -l 'function_name' src/` and update each match.

**Why:** Missing even one call site causes `TypeError` at runtime, often caught only in production.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJW7","title":"Verify call sites before refactoring function signatures","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404881+00:00","updated_at":"2026-05-03T03:56:15.404883+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve public/semi-public method signatures during extraction

When tests or external code depend on a method signature, preserve it using thin delegation stubs, `__getattr__` facades, or mixin inheritance from shared base clients. Use optional parameters to gate composition logic when decomposing large methods rather than breaking the signature.

**Why:** Refactoring that breaks public contracts forces API consumers to break as well, increasing blast radius and breaking encapsulation.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJW8","title":"Preserve public/semi-public method signatures during extraction","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404895+00:00","updated_at":"2026-05-03T03:56:15.404897+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve error isolation during refactoring

Keep per-concern try/except blocks exactly as-is when extracting code to prevent failures in one concern from blocking others. Preserve early-return cases inline in the parent rather than extracting; extract to pure module-level functions first for independent testability.

**Why:** Splitting error handling across extracted code can mask failures and violate the assumption that isolated concerns don't cascade.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJW9","title":"Preserve error isolation during refactoring","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404909+00:00","updated_at":"2026-05-03T03:56:15.404911+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mock at definition site, not import site

Mock at the definition site (e.g., `hindsight.tombstone_safe`) combined with deferred imports inside test methods—prevents import-time failures and keeps optional dependencies truly optional. When testing dependency injection, explicitly verify that the injected dependency is used instead of self-constructed.

**Why:** Import-site mocking fails if the module cannot be imported; definition-site mocking remains effective when the dependency is optional.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWA","title":"Mock at definition site, not import site","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404919+00:00","updated_at":"2026-05-03T03:56:15.404921+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use structural checks instead of isinstance() for protocol verification

Verify protocol implementation via structural subtype checks using `inspect.signature()` rather than `isinstance()`. When methods are moved during refactoring, retarget mock patches to the new location before refactoring.

**Why:** Structural checks allow duck-typed implementations to satisfy contracts; isinstance() requires explicit subclass relationships that may not exist.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWB","title":"Use structural checks instead of isinstance() for protocol verification","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404929+00:00","updated_at":"2026-05-03T03:56:15.404931+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Run existing tests unchanged after refactoring

After refactoring (especially extraction or decomposition), run all existing tests unchanged without modification. This is your primary regression test. Generated content in tests must not reference line numbers—use exact function/class names and string search for stability across refactors.

**Why:** Modifying tests during refactoring hides regressions; unchanged tests catch behavioral drift.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWC","title":"Run existing tests unchanged after refactoring","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404940+00:00","updated_at":"2026-05-03T03:56:15.404941+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use threading.Lock in thread pools, asyncio.Lock only for coroutines

Use `threading.Lock` when code runs in a thread pool (via `asyncio.to_thread()`) or is called from both sync and async contexts—`asyncio.Lock` is not thread-safe. Use `asyncio.Lock` only for coordinating pure coroutines. Extract `_unlocked()` helper variants to prevent re-entrant lock attempts.

**Why:** asyncio.Lock relies on event-loop context that is not preserved across thread boundaries, causing race conditions.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWD","title":"Use threading.Lock in thread pools, asyncio.Lock only for coroutines","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404949+00:00","updated_at":"2026-05-03T03:56:15.404951+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use crash-safe file I/O patterns for persistence

Use `file_util.append_jsonl()` wrapped in `file_lock()` for JSONL appends (includes `flush()` and `os.fsync()`). Use `file_util.atomic_write()` for critical state file updates (writes to temp, then `os.replace()` atomically). Use `os.replace()` for atomic JSONL rewrites when content is small. Lock files are zero-byte sentinels; overhead is negligible.

**Why:** Unprotected writes crash mid-flush and corrupt state; crash-safe patterns ensure atomicity and recoverability.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWE","title":"Use crash-safe file I/O patterns for persistence","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404959+00:00","updated_at":"2026-05-03T03:56:15.404961+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use claim-then-merge for async queue processing

Atomically claim items (clear/load), release lock, perform async work, re-acquire lock, reload for new items, merge with remaining, atomically write. Prevents lost entries when `write_all` overwrites file during async gap.

**Why:** Releasing the lock during async work creates a race window where other writers overwrite queued items.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWF","title":"Use claim-then-merge for async queue processing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404969+00:00","updated_at":"2026-05-03T03:56:15.404971+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve tracing context lifecycle with try/finally

Set/clear or begin/end pairs for trace context MUST execute within a single try/finally block to prevent trace state leaks. If accidentally split during refactoring, trace state leaks across issues/iterations.

**Why:** Incomplete cleanup leaves stale trace state attached to the next request, corrupting observability logs.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWG","title":"Preserve tracing context lifecycle with try/finally","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404979+00:00","updated_at":"2026-05-03T03:56:15.404981+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Keep event publishing coupled with condition checks

Event publishing stays coupled with condition checks in the same method—do not separate event logic from condition checks. Separating them creates code paths where gates block but events don't fire, breaking observability.

**Why:** Decoupled publishing hides silent failures and makes debugging impossible when conditions change without emitting signals.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWH","title":"Keep event publishing coupled with condition checks","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404992+00:00","updated_at":"2026-05-03T03:56:15.404994+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve retry state during phase result extraction

When extracting phase result classification or handling logic, preserve exact retry counter state and escalation conditions (like epic-child label swaps) from the original flow. Dry-run mode must not emit state-changing events (e.g., TRIAGE_ROUTING). Run existing tests unchanged after refactoring as the primary regression test.

**Why:** Behavioral subtleties directly impact correctness of phase state transitions and deterministic escalation.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWJ","title":"Preserve retry state during phase result extraction","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405002+00:00","updated_at":"2026-05-03T03:56:15.405003+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Maintain immutable return contracts in phase routing

Phase result routing through dispatch patterns must maintain the immutable return contract exactly (`tuple[str, str | None]` for `parse()`). Event/worker mappings must precede skip detection—implement `EVENT_TO_STAGE` and `SOURCE_TO_STAGE` together with skip detection logic.

**Why:** Changing return types or mapping precedence breaks downstream dispatch logic and causes state machine hangs.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DHZ","title":"Maintain immutable return contracts in phase routing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405016+00:00","updated_at":"2026-05-03T03:56:15.405018+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Two-round memory budget allocation

Pre-allocate budget upfront before prompt assembly in `_inject_memory()`. Round one: each section gets its minimum. Round two: remaining budget distributes proportionally by priority (from `_DEFAULT_PRIORITIES`). Allocator sets hard maxes, not predicted lengths. Wiki budget is separate and deducted before redistribution. Consume allocations explicitly after `get_allocation()`.

**Why:** Post-hoc surplus reclamation is impossible; pre-allocation prevents over-spending and balances sections fairly.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ0","title":"Two-round memory budget allocation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405027+00:00","updated_at":"2026-05-03T03:56:15.405028+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Lazy-load memory context on user action

Lazy-load memory context on explicit user action (section expand) rather than pre-fetching—avoids N+1 API calls on HITL list views. Use in-memory cache, not file-backed, for process-lifetime scope. Client-side filtering compensates for server API limitations: over-request (limit + flagged count, capped at 2x) and discard stale locally.

**Why:** Eager loading creates unbounded API calls and latency; lazy loading makes list views fast while expanding detail is still fast.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ1","title":"Lazy-load memory context on user action","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405037+00:00","updated_at":"2026-05-03T03:56:15.405038+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dedup memory items via SHA-256 hashing with threshold

Use consistent SHA-256 hashing (truncated to 16 chars) for dedup keys and recall hit tracking. Optional dedup parameter with `None` default preserves legacy behavior. Dedup via asymmetric similarity: `len(words & existing) / max(len(words), 1)` with configurable threshold (default 0.85). Higher threshold means fewer items removed.

**Why:** Semantic dedup via LLM is expensive; word-set overlap >70% catches practical duplicates without drift.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ2","title":"Dedup memory items via SHA-256 hashing with threshold","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405061+00:00","updated_at":"2026-05-03T03:56:15.405062+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Batch load scoring data once per operation

Load scoring data once per operation and reuse: call `MemoryScorer.load_item_scores()` once, reuse for all items rather than per-item. Use consistent integer ID mapping via formula: `abs(hash(str(item.get("id", ""))) % (10**9))`. Stable sort preserves original relevance order for equal scores.

**Why:** Per-item scoring multiplies I/O cost by item count; batch loading is linear and deterministic.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ3","title":"Batch load scoring data once per operation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405071+00:00","updated_at":"2026-05-03T03:56:15.405075+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Full preference learning pathway

Regex match → ConversationTurn.signal → MEMORY_SUGGESTION block → MemorySuggester → dual-write (JSONL + Hindsight) → Bank.LEARNINGS → recall_safe wrapper → turn 0 prompt injection. Expose via public `get_preference_stats()` to avoid route coupling. Distinguish ephemeral vs persistent metrics: recall attempt/hit counters are session-level; signal distribution derives from persisted state.json.

**Why:** Full pathway ensures learned preferences flow through observation → storage → inference; partial pipelines break the feedback loop.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ4","title":"Full preference learning pathway","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405085+00:00","updated_at":"2026-05-03T03:56:15.405087+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Coerce Hindsight metadata values to strings

`HindsightClient.retain()` coerces all metadata values via `str(v)`, so warnings/flags must be string `"true"`, not boolean `True`. Check via `metadata.get("warning") == "true"` which safely handles missing keys. When source is missing in historical entries, apply Tier 3 default (1.0x weight). Use `setdefault`-style logic in central injection points.

**Why:** Hindsight's string coercion loses type information; string literals prevent silent conversion bugs.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ5","title":"Coerce Hindsight metadata values to strings","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405095+00:00","updated_at":"2026-05-03T03:56:15.405097+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Conservative contradiction detection with priority

Use keyword heuristics with 40% topic overlap threshold to reduce false positives. O(n²) pairwise comparison is acceptable when n ≤ 50 items. Resolution priority: (1) provenance—human-sourced wins over agent-sourced regardless of timestamp; (2) recency—newer wins with equal provenance. Skip resources without timestamp metadata. Stale cleanup during audits removes entries no longer matching current index.

**Why:** Semantic LLM-based detection is expensive; keyword heuristics catch obvious contradictions with low false-positive rate.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ6","title":"Conservative contradiction detection with priority","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405105+00:00","updated_at":"2026-05-03T03:56:15.405107+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Memory eviction updates both item scores and items atomically

Memory eviction must update both `item_scores.json` and `items.jsonl` atomically. Admin output (e.g., `run_compact()`) should include total counts, candidate counts, and per-category breakdowns. Track original positions before re-ranking to compute boost/demotion statistics. Metrics definition must sync across all computation paths.

**Why:** Partial eviction leaves orphan scores or items, corrupting dedup keys and recall statistics.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ7","title":"Memory eviction updates both item scores and items atomically","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405115+00:00","updated_at":"2026-05-03T03:56:15.405117+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dual-file persistence: JSONL + atomic JSON

Use JSONL for append-only logs (e.g., events, observations), atomic JSON for computed state (e.g., item_scores.json, state.json). threading.Lock prevents corruption within single process; multi-process races acceptable since metrics are advisory. Complete resource cleanup before setting closed flags; idempotent `close()` via `_closed` flag guard prevents double cleanup.

**Why:** JSONL append is crash-safe; atomic JSON prevents partial-write state corruption. Dual-file separation isolates concerns.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ8","title":"Dual-file persistence: JSONL + atomic JSON","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405124+00:00","updated_at":"2026-05-03T03:56:15.405126+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Documentation consistency across CLAUDE.md and README

Keep CLAUDE.md and README in sync—they may diverge on details. ADR files must have corresponding README entries to be canonically referenceable; files without README entries become invisible. When renaming fixtures/command files, preserve namespace prefixes (hf. or hf-). Skill prompts replicated across four locations must stay in sync.

**Why:** Divergent documentation confuses users and creates hidden code paths that decay unnoticed.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ9","title":"Documentation consistency across CLAUDE.md and README","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405134+00:00","updated_at":"2026-05-03T03:56:15.405135+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Kill-Switch Convention — enabled_cb at top of _do_work

Every `BaseBackgroundLoop` subclass MUST gate `_do_work` on `self._enabled_cb(self._worker_name)` at the top of the method, returning `{'status': 'disabled'}` when false (ADR-0049). This guards against startup catchup, direct test invocation, and future scheduler refactors. A config field (e.g., staging_enabled) is an AND with enabled_cb, not a replacement. Verify: `grep -l 'async def _do_work' src/*_loop.py | xargs grep -L 'self._enabled_cb'`.

**Why:** Enabled_cb at the call site is bypassed by catchup paths; in-body checks make kill-switch behavior testable.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJA","title":"Kill-Switch Convention — enabled_cb at top of _do_work","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405143+00:00","updated_at":"2026-05-03T03:56:15.405147+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Operator Start semantics — and never hand-edit a live `state.json` (#11611)

`POST /api/control/start` is the operator saying **"run the pipeline"**, and it does exactly two things through one shared helper, `operator_start.apply_operator_start` (both branches of the route call it, so they cannot drift apart again):

1. **Clears the `operator_stopped` latch** (#11208, ADR-0135) so a relaunch's boot-time autostart and the liveness kernel stop honouring a Stop that is no longer in effect.
2. **Removes `DEFAULT_PIPELINE_WORKERS` (`triage`, `plan`, `implement`, `review`, `hitl`) from the disabled set** — in the persisted state *and* in the live orchestrator's in-memory enabled map. Every **other** entry in `disabled_workers` is a deliberate per-worker kill-switch and survives Start untouched: Start is not an "enable everything" button.

Both writes are needed because each is authoritative for a different reader: state is what a cold boot restores from, the in-memory map is what running loops consult through `enabled_cb`. `StateRestorer._restore_disabled_workers` only ever **adds** disabled flags, and `RepoRuntime.start()` reuses the same orchestrator object across a stop/start — so a state-only clear leaves a restarted line still holding `plan: False` in memory.

**Boot-time autostart applies the same transition.** `factory_autostart.maybe_autostart_host` (the `server.py` boot path, #11208) calls the same helper with `clear_latch=False` before `host_runtime.start()`. It has to: `decide_autostart` fires whenever the latch is clear and never looks at `disabled_workers`, so a kill-switch set through `/api/control/bg-worker` (which leaves `operator_stopped` false) would otherwise survive a relaunch as a running-but-dark factory — the #11611 symptom through a different door. Autostart never *clears* the latch; only an operator Start does.

What Start does **not** do: start every registered repo. The factory-level Start brings up the **host** line only (`registry.start_all` was removed — a factory must run fine with zero repos). Each repo line is started individually with `POST /api/runtimes/{slug}/start`, which applies the same pipeline-worker transition to **that line's** state and orchestrator but leaves `operator_stopped` alone — the latch is factory-level, and starting one repo must not re-arm boot autostart for the whole factory.

**The durable, supported per-worker control is the bg-worker API**, not the state file:

```bash
# port = dashboard_port (HYDRAFLOW_DASHBOARD_PORT, default 5555)
curl -sX POST localhost:5555/api/control/bg-worker \
  -H 'Content-Type: application/json' -d '{"name":"plan","enabled":false}'   # kill-switch ON
curl -sX POST localhost:5555/api/control/bg-worker \
  -H 'Content-Type: application/json' -d '{"name":"plan","enabled":true}'    # back on
curl -sX POST localhost:5555/api/control/start                               # latch + pipeline
curl -s localhost:5555/api/control/status  | jq '.operator_stopped'          # the latch
curl -s localhost:5555/api/system/workers  | jq '.workers[] | {name, enabled}'
```

Add `?repo=<slug>` to scope any of them to a registered line instead of the host.

**Never edit the state file (`<data_root>/<repo-slug>/state.json`, i.e. `.hydraflow/<owner>-<repo>/state.json`) on disk while a factory process is alive.** `StateTracker` holds the whole document in memory and rewrites the file on the next `save()` — every accessor (`set_disabled_workers`, `set_operator_stopped`, any worker heartbeat) persists the *in-memory* copy, so the hand edit is silently clobbered, usually within seconds. Observed 2026-08-21: a pre-boot edit setting `disabled_workers: []` came back as `["plan","triage"]` after boot. Stop the process first, or — better — use the API above, which writes both halves.

**Why:** an operator pressing Start reasonably expects the board→READY path to run. The registry branch used to clear only the latch, so the 2026-08-21 launchd boot returned `{"status":"started"}` with `disabled_workers` still `["plan","triage"]` — a factory that looked started and moved nothing, until each worker was re-enabled by hand.

```json:entry
{"id":"OPERATOR-START-SEMANTICS-PIPELINE-REENABLE-001","source_type":"manual","topic":"patterns","tags":["control-routes","operator-start","kill-switch","disabled-workers","operator-stopped","state-json","dashboard","launchd","adr-0135","adr-0049"],"rule":"POST /api/control/start applies one shared transition (operator_start.apply_operator_start) on both branches: clear the operator_stopped latch AND re-enable DEFAULT_PIPELINE_WORKERS (triage/plan/implement/review/hitl) in BOTH the persisted disabled set and the live orchestrator's in-memory enabled map; every other disabled worker is a durable kill-switch and survives. Start brings up the host line only; POST /api/runtimes/{slug}/start and boot-time factory_autostart.maybe_autostart_host apply the same worker transition with clear_latch=False (only an operator Start clears the latch). Per-worker control is POST /api/control/bg-worker {name, enabled} (+ ?repo=<slug>). Never hand-edit a live state.json: StateTracker rewrites the whole document from memory on the next save.","anti_pattern":"Clearing only the latch on one Start branch (the registry/production path) so Start reports 'started' with disabled_workers still [plan, triage] and no board->READY path; writing only state and not the live orchestrator's enabled map (StateRestorer only ADDS disabled flags, and RepoRuntime.start() reuses the same orchestrator object); letting boot-time autostart skip the transition (decide_autostart never inspects disabled_workers, so a bg-worker kill-switch survives a relaunch as a running-but-dark factory); or editing .hydraflow/<repo>/state.json on disk while the factory runs and expecting it to stick","code_refs":["src/operator_start.py:apply_operator_start","src/dashboard_routes/_control_routes.py","src/dashboard_routes/_state_routes.py","src/factory_autostart.py:maybe_autostart_host","src/state/_worker.py","src/state/_control.py","src/state_restorer.py","src/bg_worker_manager.py","tests/test_operator_stopped_latch_routes.py","tests/regressions/test_start_reenables_pipeline_workers_11611.py","tests/scenarios/test_operator_stop_latch_kernel_scenario.py"],"source_issue":11611,"added":"2026-08-22"}
```


## HITL Escalation Channel — hitl-escalation label

Trust loops never page humans except by filing a GitHub issue with the `hitl-escalation` label (ADR-0045). File exactly one escalation issue and stop re-filing until the operator resolves it. Body must promise: 'closing this issue clears the attempt counter'. Threshold-based escalation checks the counter BEFORE incrementing—past-threshold ticks are no-ops until reconciliation. Anomalies file with sub-labels (rc-red-attribution-unsafe, principles-stuck) for operator targeting.

**Why:** Multiple escalation issues overwhelm operators; single issue + counter reset via closure enforces discipline.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJB","title":"HITL Escalation Channel — hitl-escalation label","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405157+00:00","updated_at":"2026-05-03T03:56:15.405158+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Underscore-prefixed names are not public imports

If a symbol is imported from another module, it is part of that module's public API and must not start with `_`. Leading underscore is Python's 'module-internal' convention; crossing the boundary trips pyright's `reportPrivateUsage` warnings. Right: `from plugin_skill_registry import parse_plugin_spec` (rename from `_parse_plugin_spec`).

**Why:** Private-symbol imports confuse readers about intent and fail strict linter checks.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJC","title":"Underscore-prefixed names are not public imports","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405166+00:00","updated_at":"2026-05-03T03:56:15.405177+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use bare _ for truly unused loop variables

Python's convention for unused variables is bare `_`, not `_name`. Pyright treats `_name` as a named variable and flags it as unused regardless. Right: `for _, name, marketplace in specs: ...` Wrong: `for _lang, name, marketplace in specs: ...`

**Why:** Bare `_` is universally understood; `_name` is ambiguous and fails linting.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJD","title":"Use bare _ for truly unused loop variables","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405186+00:00","updated_at":"2026-05-03T03:56:15.405188+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## DRY principle for frontend constants and styles

Shared constants live in `ui/src/constants.js`, type definitions in `ui/src/types.js`. Colors are CSS custom properties in `ui/index.html` `:root`, accessed via `ui/src/theme.js`—always use `theme.*` tokens, never raw hex or rgb values. Extract shared styles to reusable objects when used 3+ times.

**Why:** Duplication causes maintenance burden and style drift; single-source-of-truth constants sync across the UI.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJE","title":"DRY principle for frontend constants and styles","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405199+00:00","updated_at":"2026-05-03T03:56:15.405201+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Worktree workflow and conventions

Worktrees live at `../hydraflow-worktrees/` (sibling to repo root). Name by issue: `issue-{number}/` or descriptively for other changes. Worktrees get independent venvs (`uv sync`), symlinked `.env`, and pre-commit hooks. Stale worktrees from merged PRs should be pruned periodically with `git worktree prune`. Cleanup: `make clean` removes all worktrees and state.

**Why:** Standard naming and location make worktree state discoverable and prevent scattered work.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJF","title":"Worktree workflow and conventions","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405209+00:00","updated_at":"2026-05-03T03:56:15.405210+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Run and dev commands

`make run` starts backend + Vite frontend. `make dry-run` shows actions without executing. `make clean` removes all worktrees and state. `make status` shows current HydraFlow state. `make hot` sends config update to running instance.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJG","title":"Run and dev commands","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405218+00:00","updated_at":"2026-05-03T03:56:15.405220+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Why memory/observation is harnessed, not autonomous

No autonomous mutation of prompts/skills in-repo. Observation data is lightweight and local. Retros produce explicit artifacts for human review. Promotion into durable memory goes through `/hf.memory` and HITL.

**Why:** Harnessed design prevents drift and maintains human visibility into what the system learns.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJH","title":"Why memory/observation is harnessed, not autonomous","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405227+00:00","updated_at":"2026-05-03T03:56:15.405229+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Telemetry layer — OTel for traces, Sentry for exceptions

HydraFlow uses **OpenTelemetry → Honeycomb** for distributed tracing (per-phase / per-loop-tick / per-port-call spans with `hf.*` business attributes for BubbleUp-ready dimensionality) and **Sentry** for automatic uncaught-exception capture and stack-trace fingerprinting. The two are layered, not overlapping. Sentry's `before_send` hook filters transient errors; OTel decorators (`@runner_span()`, `@loop_span()`, `@port_span(name)`) emit spans that wrap business calls without altering control flow — every span operation is wrapped in `_safe_*` helpers that swallow telemetry exceptions while always re-raising business exceptions. `init_otel(config)` is called once from `server.py:main()` after `_init_sentry()`. When `config.otel_enabled=False`, the decorator stack is byte-identical to no decorators (regression-tested). All `hf.*` attributes flow through `add_hf_context()` — single source of truth, enforced by `tests/architecture/test_otel_invariants.py`. See ADR-0055 for the full architectural decision.

**Why:** Two telemetry channels with explicit roles prevent the failure mode where a single channel becomes "everything but really good at nothing." Sentry catches what we forgot to instrument; OTel gives us causal traces we can query and BubbleUp on. Phase B's anomaly-detection loop will read from Honeycomb; the question of whether to retire Sentry is deferred to that point with 30 days of data.


```json:entry
{"id":"01KQOTEL55HC2026B0PHASEA001","title":"Telemetry layer — OTel for traces, Sentry for exceptions","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-06T20:50:00.000000+00:00","updated_at":"2026-05-06T20:50:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## Branch protection — rulesets that enforce the two-tier model (ADR-0042)

`main` and `staging` are protected by GitHub **rulesets** (the modern replacement for classic branch protection rules), not by classic branch-protection settings. Always read these via `gh api /repos/T-rav/hydraflow/rulesets/<id>`, never via the classic `/branches/<name>/protection` endpoint (it returns 404 even when the branch is protected).

| Ruleset | ID | Target | Allowed merge methods | Required status checks |
|---|---|---|---|---|
| `main protect` | `15468404` | `refs/heads/main` (explicit ref, not `~DEFAULT_BRANCH` — `staging` is the GitHub default branch, `main` is the release branch) | `["merge"]` only — squash is rejected (ADR-0042 §Decision: squash from a long-lived integration branch produces a growing-diff regression). RC promotion uses `gh pr merge --merge`. | Full standard CI set + RC promotion gate: `Tests`, `Lint & Format`, `Type Check`, `Security Scan`, `Smoke Tests`, `Scenario Tests`, `Regression Tests`, `Principles Audit`, `quality (.)`, `quality (src/ui)`, **`Resolve RC PR`**, **`Browser Scenarios`**, **`Trust Gate (adversarial corpus, fixture mode)`**, **`Sandbox (rc/* promotion PR full suite)`**. The bold four are the MockWorld + e2e gate that only applies to `rc/* → main` PRs. (Source of truth: [`gates.toml`](../standards/branch_protection/gates.toml); this list is generated.) |
| `staging protect` | `16066429` | `refs/heads/staging` | `["squash", "merge"]` — agent PRs squash by default; merges accepted for cross-branch fixups. | **2 always-on checks**: `Detect Changes`, `discover-projects`. (ADR enforcement is no longer a required check of its own: ADR-0136 puts it inside the existing `Tests` lane as `test_no_unresolved_adr_citations`. It was briefly the `adr_touchpoint_auditor` caretaker loop, ADR-0056 — now superseded.) Heavy CI (`Tests`, `Lint`, `Type Check`, etc.) is path-filtered to SKIPPED for docs-only PRs and would block forever if required. Failures still appear in the PR rollup for visible-but-not-enforced gating. The `CI Gate` umbrella job (`ci.yml`, `if: always()`, `needs:` all conditional jobs) now aggregates these path-filter-safe; it runs visibly and can be promoted to the single required context (see `docs/standards/branch_protection/ADDING-A-GATE.md`). |

Both rulesets also enforce: no deletion, no force-push, PR required (no direct pushes). `main protect` additionally enforces code-quality severity=`errors` and code-scanning CodeQL high-or-higher; `staging protect` does NOT (staging is fast integration, and the CodeQL/code-quality gate is enforced on the `rc/* → main` promotion PR instead).

**CodeQL false-positive policy (issue #9143).** A persistent CodeQL FP on first-party redaction/sanitizer code is fixed with a *version-controlled* mechanism, never a one-off UI dismissal (which suppresses a single alert instance on a single PR and re-fires on the next promotion PR). Preferred, in order: (1) a Models-as-Data sanitizer model (`barrierModel`) under `.github/codeql/` **if the flagging query consumes MaD barriers** — many do (the injection queries), but some don't: `py/clear-text-storage-sensitive-data`'s barrier set is a hardcoded QL `Sanitizer` class with no `barrierModel`/`ModelOutput` hook, so a MaD/neutral model is inert for it (and neutral models never override an analyzed first-party body); (2) if the query has no MaD barrier hook, a **scoped `# codeql[<rule>]` inline suppression at the sink** plus the `advanced-security/dismiss-alerts` step in `codeql.yml` — GitHub code scanning records suppressions in SARIF but does not natively dismiss from them. Suppress at the sink only, never the whole file/query. See the `scrub_secrets` case (ADR-0085, `file_util.append_jsonl`).

Repo-level settings:
- `default_branch=main` (release reference; integration is `staging`)
- `allow_auto_merge=true` — required for `gh pr merge --auto` and for `StagingPromotionLoop` to queue auto-merges on RC PRs
- `allow_squash_merge=true`, `allow_merge_commit=true`, `allow_rebase_merge=true` — methods are gated per-branch by ruleset, not at repo level

**Merge mechanism — process-driven, not auto-merge.** PRs are merged by the process that opened them (`AgentRunner` for agent PRs into `staging`, `StagingPromotionLoop` for RC PRs into `main`, humans for human PRs). GitHub's `--auto` flag is not the path — auto-merge is fire-and-forget and silently abandons the PR on conflict, retired check, or race. The factory needs the process to stay attached through merge: poll CI, try merge, react to failures (file issue, retry, escalate). `allow_auto_merge=true` is set (so humans can opt into it for low-risk PRs) but unused by the standard flow.

**Apply / audit / re-apply** with `scripts/setup_branch_protection.py` — idempotent, works on any HydraFlow-format repo:

```bash
python scripts/setup_branch_protection.py --audit             # exit 1 on drift
python scripts/setup_branch_protection.py                     # dry-run apply
python scripts/setup_branch_protection.py --apply             # PUT/POST + create staging branch + set allow_auto_merge
python scripts/setup_branch_protection.py --repo owner/name --apply   # cross-repo
```

Canonical rulesets are versioned JSON at [`docs/standards/branch_protection/`](../standards/branch_protection/) — diff those, not the live API, to know what *should* be there.

**Why:** Encoding the decision in two rulesets (rather than docs alone) means the GitHub UI itself rejects squash-into-main and direct-push violations — convention that becomes infrastructure. The required-check sets enforce that nothing reaches `main` without the full MockWorld + e2e sandbox suite, and nothing reaches `staging` without the full standard CI gate.


```json:entry
{"id":"01KQRULESET2026B0PHASE2002","title":"Branch protection — rulesets that enforce the two-tier model (ADR-0042)","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-07T03:55:00.000000+00:00","updated_at":"2026-05-07T03:55:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## AdversarialRetryLoop pattern — shared contract for dissent stages

The earlier-adversarial pipeline (ADR-0064) routes every dissent stage — `AssumptionSurfacer`, `DiscoveryCouncil`, `PlanCouncil`, pre-impl `SpecJudge`, and the retrofitted Shape `Challenger`/`ExpertCouncil` — through a single shared retry primitive: `src/adversarial_retry_loop.py:AdversarialRetryLoop`.

The contract is uniform:

1. **Three-retry budget per stage.** Voter surfaces concerns → host agent (planner / surfacer / Shape-runner) re-runs with concerns attached → re-vote. Repeat up to 3 retries.
2. **Oscillation detection.** If round N+1's concerns are structurally equal to round N's (`Concern.fingerprint()` equality), short-circuit as `OscillationDetected` — don't burn the full budget on a fixed-point disagreement.
3. **Wide-loop forwarding fallback.** Budget exhaustion or oscillation doesn't gate the issue forever. Unresolved `Concern`s are written to `AdversarialState.pending_concerns` and the wider lifecycle (Plan Reviewer, downstream stages) sees them as `must_address_by` constraints. Carryover concerns that survive to merge emit `ShippedWithKnownGap` and become wiki entries via `src/wiki_carryover.py`.

**Use this pattern when:** adding a new adversarial voter, a new contrarian judge, or any agent whose role is to *surface dissent the host can't see by itself*. Don't reinvent the retry-with-budget-plus-fallback wheel; instantiate `AdversarialRetryLoop` and pass the voter + host as callables.

**Don't use this pattern when:** the agent is a normal validator with a yes/no contract (use a plain assertion or gate), or when the operation must block until resolved (the wide-loop fallback is load-bearing — without it the dark factory deadlocks).

Observability: `run_with_metrics()` returns per-invocation metrics that flow through the `AdversarialStageStarted` / `AdversarialStageCompleted` / `AdversarialRetryExhausted` / `OscillationDetected` EventBus events.

**Why:** A uniform contract means once you understand one adversarial stage, you understand all of them. Adding a new voter is a localised change — write the voter, plug it into `AdversarialRetryLoop`, register the events. No bespoke retry logic per stage.


```json:entry
{"id":"01KRADV2026B0PHASE0001","title":"AdversarialRetryLoop pattern — shared contract for dissent stages","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-17T00:00:00.000000+00:00","updated_at":"2026-05-17T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## `LoopFitness` contract and AST ratchet (ADR-0093)

Every `BaseBackgroundLoop` subclass must implement `loop_fitness(self, ctx: FitnessContext) -> LoopFitness`. This is the bespoke-fitness contract on each loop, introduced in ADR-0093.

**The purity constraint.** `loop_fitness()` must read only from `ctx`. No network calls, no clock reads, no mutable `self` state, no globals. `FitnessContext` is a frozen, data-only Pydantic model (window bounds, pre-filtered event history, issue snapshot, optional cost). Purity is the keystone: the same function can score live history now and replay candidate configs later in the deferred hill-climb optimizer — a live client call would silently score against today's repo instead of the historical snapshot.

**Declaring the right kind.** Return `LoopFitness` with `kind=FitnessKind.SCORED` for loops with a meaningful 0–1 objective (proposer loops, auditor loops, monitor loops). Return `FitnessKind.HOUSEKEEPING` for maintenance-only loops (`WorkspaceGCLoop`, `DiagramLoop`, etc.) that have no acceptance lifecycle — this is a valid, explicit declaration, not a missing measurement. A `score` is never required; a declaration always is.

**The no-leaderboard rule.** The normalized `score` field is valid for intra-loop trend tracking (this loop today vs. 30 days ago) and intra-loop config ranking (future optimizer). It is invalid to rank loops against each other. A GC loop reclaiming 12 branches is not "better" or "worse" than a proposer loop with 0.6 acceptance; the archetypes are incomparable by construction.

**Confidence by `sample_count`.** `Confidence.OK` is only set when `sample_count >= min_samples`. The threshold is cadence-aware (#9841): `fitness_min_samples` (default 5, right-sized to observed proposer throughput of 6–14 filed per 30-day window) is capped per-loop by `loop_fitness.cadence_min_samples` at the loop's achievable tick count (`window / interval`, never below `MIN_SAMPLES_FLOOR = 3`). The old global default of 20 was mathematically unreachable for daily-cadence loops, so every scorecard row sat in `INSUFFICIENT_DATA` forever and the scorecard carried no signal. `INSUFFICIENT_DATA` remains the honest state for loops that genuinely filed too little in the window — it keeps the future optimizer's hands off loops with thin evidence.

**The AST ratchet.** `tests/test_loop_fitness_completeness.py` discovers every `BaseBackgroundLoop` subclass via AST and fails if `loop_fitness` is not defined directly on it (not just inherited). Existing loops before ADR-0093 are grandfathered by the default implementation on `BaseBackgroundLoop` itself. New loops cannot ship without an explicit override.

**Why:** A fitness function that touches live state would corrupt the offline optimizer's replay. The ratchet prevents silent omission. The `HOUSEKEEPING` escape prevents garbage metrics for maintenance loops.


```json:entry
{"id":"01JZ9FK3C0M04HYR42BF44W0D4","title":"`LoopFitness` contract and AST ratchet (ADR-0093)","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-06-30T00:00:00.000000+00:00","updated_at":"2026-06-30T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## Opt-in ultra deep-review tier (ADR-0109)

Expose a deep multi-reviewer "ultra" pass as an opt-in review-phase option (#10555). The **cloud** `/code-review ultra` tier has no programmatic entry point — it is client-side, user-triggered, and separately billed — so the tier instead wraps the locally-installed `code-review` plugin dispatched headlessly through the same seam as the post-verify advisor. Load-bearing: build the command with `build_agent_command(..., isolate_user_settings=False)`; `True` strips the `--plugin-dir` flags so the plugin slash-command would not resolve. Cost gate is three AND-ed conditions: `config.review_ultra_enabled` (default OFF) AND (`review:ultra` issue label OR high-blast-radius diff when `review_ultra_auto_high_blast`). Findings scored ≥80 flip the verdict to `REQUEST_CHANGES` (reusing the existing fix hand-back); sub-threshold findings post as a PR comment. Credit-exhaustion propagates via `reraise_on_credit_or_bug`; any other spawn failure fails soft to a degraded result that leaves the verdict intact. Logic lives in `src/ultra_review.py`; the phase adds only a thin runner adapter + fold helpers.

**Why:** A deep adversarial pass whose high-confidence findings actually change merge outcomes, without cost blow-up — the default-off dial plus three AND-ed triggers keep the expensive fan-out off every PR, and a test asserts zero dispatch at defaults.


```json:entry
{"id":"01KYEF98BHWVZEC1S5YEBDJPK3","title":"Opt-in ultra deep-review tier (ADR-0109)","topic":null,"source_type":"compiled","source_issue":10555,"source_repo":null,"created_at":"2026-07-25T00:00:00.000000+00:00","updated_at":"2026-07-25T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## Release policy — stable tags vs the rolling main tip

HydraFlow ships two things that are easy to confuse. **`main` is the rolling integration tip**: `StagingPromotionLoop` cuts an `rc/YYYY-MM-DD-HHMM` PR every `rc_cadence_hours` (default 4h) and merges it once the RC gate (`RC Promotion Scenario` + sandbox shards) is green (ADR-0042). Every `main` SHA has passed that gate, but `main` carries no compatibility promise between promotions and is not a release. **A stable tag (`vX.Y.Z`) is a promise**: the milestone that names it has zero open issues (no open data-loss or wrong-branch paths, no false-close blind spots), `main` CI and the last `RC Promotion Scenario` run are green on the tagged SHA, zero open high-severity code-scanning alerts, no open P0, and the version in `pyproject.toml` / `src/__init__.py` / `src/ui/package.json` matches the tag. Downstream HydraFlow-format repos (amplifier, harvestd, Signal Room, every `make stamp` bootstrap) pin a tag — `git checkout vX.Y.Z` — never `main` (README → "Install a pinned release"; per-release notes in `CHANGELOG.md`). The tag always points at a **promoted `main` SHA**: never at `staging`, never at whatever `HEAD` the operator's checkout happens to be on.

**The cut recipe** (first used for v1.0.0, #11520):

```bash
# (a) preconditions — every line must come back clean
gh issue list --milestone "<milestone>" --state open --json number --jq length                     # 0
gh run list --branch main --workflow CI --limit 1 --json conclusion --jq '.[0].conclusion'          # success
gh run list --workflow "RC Promotion Scenario" --limit 1 --json conclusion --jq '.[0].conclusion'   # success
gh api 'repos/{owner}/{repo}/code-scanning/alerts?state=open&severity=high' --jq length             # 0
gh issue list --label P0 --state open --json number --jq length                                     # 0

# (b) version-bump + CHANGELOG PR → staging; merge it; let the next RC promote it to main
#     touches pyproject.toml, src/__init__.py, src/ui/package.json (+ package-lock.json), uv.lock, CHANGELOG.md
gh pr create --base staging --title "chore(release): vX.Y.Z — <name>: version bump, CHANGELOG, pinned-install docs (refs #<release issue>)"

# (c) tag the PROMOTED main SHA and publish the release — by hand
git fetch origin main
git log -1 --format='%H %s' origin/main          # confirm this SHA carries the bump (RC promotion of the bump PR)
git tag -a vX.Y.Z <promoted main sha> -m "vX.Y.Z — <name>"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z — <name>" --notes-file <the CHANGELOG section for vX.Y.Z>
```

**Nothing cuts the tag for you.** ADR-0011 describes a release-on-epic-close trigger, but `EpicCompletionChecker._do_close_epic` stopped calling `_create_release_for_epic` in #2689 (pinned by `tests/test_release.py::test_no_release_on_epic_close`), and `EpicManager.release_epic` only merges the bundle and flips `released` — the primitive has no production caller (#11569), and before #11517 it would have tagged the factory checkout `HEAD` rather than `main`. Until #11569 re-attaches the primitive to a chosen trigger, step (c) is manual: run it in a checkout whose `origin/main` was just fetched and pass the SHA explicitly — a bare `git tag vX.Y.Z` tags the current `HEAD`, which on a factory host is `staging` or an agent branch.

**Why:** Downstream repos need a SHA they can name and trust; "latest main" moves every 4h, and the only automatic tagging path was found to be caller-less and pointed at the wrong ref class (#11517, #11569). Making the promise explicit (milestone clear + gates green + tag on promoted `main`) and the mechanism manual-until-wired keeps the tag honest.


```json:entry
{"id":"RELEASE-POLICY-STABLE-TAG-001","source_type":"manual","topic":"patterns","tags":["release","tag","semver","main","staging","rc-promotion","downstream","adr-0042","adr-0011","changelog"],"rule":"main is the rolling integration tip (RC-promoted every rc_cadence_hours, ADR-0042), not a release. A stable vX.Y.Z tag promises: milestone at 0 open, main CI + last RC Promotion Scenario green, zero open high code-scanning alerts, no open P0, version files match the tag. Cut it by hand on the promoted main SHA after the bump PR lands via RC: fetch origin main, tag -a <main sha>, push the tag, gh release create with the CHANGELOG section. The ADR-0011 epic-close trigger has not fired since #2689 (#11569) — nothing tags automatically.","anti_pattern":"Telling downstream repos to build on main, or running a bare `git tag vX.Y.Z` without an explicit ref so the tag lands on staging / a checkout HEAD instead of the promoted main SHA","code_refs":["CHANGELOG.md","README.md","pyproject.toml","src/__init__.py","src/epic.py:EpicCompletionChecker._create_release_for_epic","docs/adr/0042-two-tier-branch-release-promotion.md","docs/adr/0011-epic-release-creation-architecture.md"],"source_issue":11520,"added":"2026-08-21"}
```

## Quality gate tiers — the implementer runs lock-free, CI is the full gate (#11568)

`make quality` runs under a host-wide advisory lock (`scripts/quality_host_lock.py`, #11400): two concurrent full suites on one box oversubscribe it, xdist workers get killed mid-run and the survivor reports failures that pass in isolation (#11219), so the second run waits. That lock guards the **host**, not the code. Routing the implementer's post-build verification through it serialized every worker after every build and every quality-fix round — 10–15 min queued per round with three workers on one lock, while the dashboard reported `max_workers` parallelism the lock removed (measured in #11568: implement attempts per issue 1.2 → 2.2). Operator ruling 2026-08-21: take `make quality` off the host lock on the implement path; CI (9–11 min) is the full gate.

**Three tiers, each honest about what it checks:**

| Who | Command | Lock | Suite |
|---|---|---|---|
| Implementer post-build gate (`AgentRunner._verify_quality`, every build + every quality-fix round) | `make quality-lite`, then `make test-impacted BASE_REF=origin/<base> IMPACTED_ARGS=--bounded` (repos without the target: `test_command`) | none | lint + pyright + bandit, then the tests the diff plausibly touches — **bounded**: `--bounded` never emits `__ALL__`, a high-fanout diff keeps its name-mapped tests + the floor and defers the full suite to CI |
| CI on the PR | the workflow lanes | one suite per runner | full — the merge gate |
| Humans / operators, HITL + diagnostic runners (`BaseRunner._verify_quality`), the RC gate | `make quality` | host lock | full, one at a time by design |

The implementer prompt already says "`make quality-lite` as a sense check; CI runs the full test suite" and `.githooks/pre-push` already runs `make quality-lite` — the runner's gate now matches both. `implement_full_quality_gate=True` (`HYDRAFLOW_IMPLEMENT_FULL_QUALITY_GATE`, System tab › CI & Quality) restores the locked full run for a repo that needs it.

**Why not "N concurrent unlocked full suites":** that is the #11219 thrash the lock exists to prevent; "off the lock" means "do not run the full suite locally", not "run it without the guard". **Why not `max_workers` = lock width:** it would make the dashboard truthful but keep the 10–15 min round — the waste is the round, not the lie.

```json:entry
{"id":"QUALITY-GATE-TIERS-IMPLEMENT-LOCK-FREE-001","source_type":"manual","topic":"patterns","tags":["quality-gate","host-lock","implementer","quality-lite","test-impacted","ci","throughput","max_workers","adr-0044"],"rule":"The implementer's post-build gate (AgentRunner._verify_quality, after every build and every quality-fix round) runs lock-free: make quality-lite, then make test-impacted IMPACTED_ARGS=--bounded (never __ALL__; repos without the target run test_command). CI is the one full-suite gate per PR. Humans, HITL/diagnostic runners and the RC gate keep the host-locked make quality — the lock guards the host and those paths are one-at-a-time. implement_full_quality_gate=True restores the locked full run.","anti_pattern":"Routing every implementer's post-build verification through the host-locked full make quality so max_workers workers serialize on one lock (10-15 min per quality-fix round) — or 'fixing' it by running N unlocked full suites concurrently, which is the #11219 host thrash the lock exists to prevent","code_refs":["src/agent.py:AgentRunner._verify_quality","src/base_runner.py:BaseRunner._verify_quality","scripts/impacted_tests.py","scripts/quality_host_lock.py","Makefile","src/config.py","tests/regressions/test_issue_11568_implement_quality_off_host_lock.py","tests/scenarios/test_implement_quality_gate_scenario.py"],"source_issue":11568,"added":"2026-08-21"}
```

## A gate's rejections are outcome-censored — calibrate what you can, say what you cannot (#11593)

The escape ledger keys every defect to an `originating_pr`: it observes **merged** work only. So a run a gate *rejects* can never acquire an outcome — the diff never merged, no escape can ever attach to it, and waiting longer changes nothing. This is the **selective-labels** problem, and it means the question "what is this gate's precision?" is *not identifiable* from the escape ledger no matter how much data accumulates. `src/adequacy_calibration.py` makes that structural, not rhetorical: `to_judge_verdicts` keys rejections with `judge_calibration.subject_for_issue` (the helper documented as *not* joining to escapes), so `judge_calibration.resolve` drops every rejection and `Identifiability.n_rejections_resolved` reports the honest `0`.

**What an instrument in this position reports instead** — four quantities that ARE derivable, each labelled with what it can support:

| Quantity | Answers | Cannot answer |
|---|---|---|
| Accept-arm proper score (`judge_calibration.score_judge` over passed-and-merged work) | is the gate too **loose**? | anything about strictness — same selection bias |
| Recovery (did the gated issue reach a later successful run?) | what the rejection **cost** | whether it was right |
| **Demand stationarity** (`demand_stationarity`) | does the gate hold a **fixed bar** across retries? | — needs no ground truth at all |
| Finding taxonomy (`grade_finding`, `is_out_of_remit`) | is the demand **locatable** and in remit? | whether the gap is real |

Demand stationarity is the load-bearing one precisely because it needs no outcome: group a gate's rejections by subject, order them in time, and score each consecutive pair by the Jaccard overlap of its finding tokens *after stripping the gate's own vocabulary* (`untested`, `missing`, `coverage`, `branch`, `case`… — words in nearly every finding that say nothing about **which** gap is demanded, so leaving them in manufactures overlap). Disjoint successive demands mean the implementer satisfied the stated bar and was rejected anyway: the gate is resampling from an unbounded space of possible gaps, and no finite amount of work satisfies it. Measured on the August-2026 implement corpus: 9 of 15 consecutive re-rejections [36 %, 80 %] demanded something entirely new, mean substantive overlap 0.04.

**On the accept arm, "no escape recorded" is a reading, not a resolution.** Escapes surface with a lag, so a merge from an hour ago has had no chance to accumulate one; scoring it clean credits the gate for work nothing has checked yet. `resolved_escapes` therefore resolves an attributed escape *bad immediately* but holds a clean reading unresolved until its `closed_at` clears ADR-0127's `DEFAULT_GRACE_WINDOW` — and treats a **missing** `closed_at` as unresolvable too, because "we cannot date it" is the same epistemic state as "too recent", never "old enough". That is what makes `now` load-bearing in the entrypoint rather than decoration.

**Report the identifiability verdict before any rate.** While `Identifiability.under_determined` is set, the point estimates describe the corpus but do **not** license a change to the gate. Every rate carries a Wilson interval (not the normal approximation — these denominators are small and the rates sit near 0 or 1); every degenerate case is `None`, never a fabricated `0.0`. And a lexical proxy is named as one: `SuspectRejection` means "the stated reason reads weak on its face, go read it", never "this rejection was wrong".

```json:entry
{"id":"GATE-REJECTIONS-OUTCOME-CENSORED-CALIBRATION-001","source_type":"manual","topic":"patterns","tags":["calibration","judge-calibration","adr-0127","escape-ledger","selective-labels","test-adequacy","instrument","wilson-interval","identifiability","measure-the-machinery"],"rule":"A gate's REJECT arm is outcome-censored: the escape ledger keys defects to an originating_pr, so rejected work (which never merges) can never resolve to good/bad and the gate's precision is not identifiable, however much data accumulates. An instrument here reports the identifiability verdict FIRST, keys rejections with judge_calibration.subject_for_issue so the zero is measured rather than argued, and falls back to the quantities that need no ground truth — demand stationarity (Jaccard overlap of consecutive re-rejections on one subject, gate vocabulary stripped) and finding taxonomy (locatable referent? in remit?) — each with a Wilson interval and None for every degenerate case. On the ACCEPT arm an attributed escape resolves bad immediately, but an escape-free reading resolves good only once its closed_at clears ADR-0127 DEFAULT_GRACE_WINDOW; a reading with no closed_at stays unresolved rather than being treated as aged.","anti_pattern":"Joining a gate's rejections against the escape ledger and reporting the resulting 'precision'; scoring a just-merged PR as clean the instant it lands because no escape has been attributed yet (escapes surface with a lag — that is a reading, not a resolution), or resolving unattributed subjects as clean, both of which credit the gate for work nothing checked; also: computing token overlap between two rejections without stripping the gate's own vocabulary, which manufactures similarity between demands that share nothing but the words 'untested' and 'coverage'","code_refs":["src/adequacy_calibration.py","src/judge_calibration.py:subject_for_issue","src/judge_calibration.py:score_judge","scripts/calibrate_adequacy_gate.py","tests/test_adequacy_calibration.py","tests/test_calibrate_adequacy_gate.py","docs/adr/0127-judge-calibration.md"],"source_issue":11593,"added":"2026-08-22"}
```
