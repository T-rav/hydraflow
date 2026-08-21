# Dependencies


## Use TYPE_CHECKING guards to break circular imports

Use `if TYPE_CHECKING:` blocks and PEP 563 (`from __future__ import annotations`) to defer imports that create cycles. Type hints are evaluated at type-check time, not runtime, allowing the import cycle to break.

**Why:** Circular imports at module level cause runtime failure; TYPE_CHECKING breaks the cycle without losing type information.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKD","title":"Use TYPE_CHECKING guards to break circular imports","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811703+00:00","updated_at":"2026-05-03T03:52:34.811721+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use callbacks instead of class refs for runtime dependencies

When classes have runtime circular references, inject callback functions instead of importing the class directly. Example: `get_progress=epic_reporter.get_progress` passed to constructor instead of importing Reporter class.

**Why:** Defers resolution until initialization, avoiding import-time cycles and making dependency direction explicit in function signatures.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKE","title":"Use callbacks instead of class refs for runtime dependencies","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811755+00:00","updated_at":"2026-05-03T03:52:34.811757+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Degrade gracefully when optional dependencies fail

Wrap optional dependency usage in broad exception handlers with safe defaults; never re-raise. Example: `except Exception: return safe_default # noqa: BLE001` for optional Hindsight recall or memory injection.

**Why:** Failures in optional features must not interrupt the pipeline; graceful degradation preserves core functionality when optional systems fail.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKF","title":"Degrade gracefully when optional dependencies fail","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811769+00:00","updated_at":"2026-05-03T03:52:34.811771+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Protocol for optional dependency interfaces

Define Protocol interfaces instead of concrete imports for optional dependencies. Callers use duck typing without importing the optional module.

**Why:** Avoids hardcoding imports of optional packages into main code; allows swapping implementations and testing without the optional dependency installed.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKG","title":"Use Protocol for optional dependency interfaces","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811779+00:00","updated_at":"2026-05-03T03:52:34.811781+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Define shared artifacts once, import everywhere

Create artifacts (schemas, constants, routes) in a single module and import them everywhere they're used. Don't duplicate definitions across files.

**Why:** Prevents divergence where the same artifact has multiple versions in different parts of the codebase.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKH","title":"Define shared artifacts once, import everywhere","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811788+00:00","updated_at":"2026-05-03T03:52:34.811790+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Extract parallel-independent classes before dependent ones

When extracting coordinators from a god class, identify classes with zero cross-dependencies and extract them in phase 1; handle phase ordering for classes with dependencies. Map dependencies as a task graph to prevent parallel work from being blocked.

**Why:** Unblocks parallel extraction and makes dependency constraints explicit.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKJ","title":"Extract parallel-independent classes before dependent ones","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811799+00:00","updated_at":"2026-05-03T03:52:34.811801+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify extraction completeness in two stages

Stage 1: Check function signatures, return types, and other references in the source file. Stage 2: Grep the codebase for old names in imports, docs, comments, fixtures.

**Why:** Stage 1 catches unused local imports; Stage 2 catches references in tests, dynamic imports, and external modules that single-file grep misses.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKK","title":"Verify extraction completeness in two stages","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811810+00:00","updated_at":"2026-05-03T03:52:34.811813+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Register FastAPI catch-all routes last

Use `/{path:path}` route at the end of route registration. Register more specific routes first.

**Why:** Catch-all routes match anything; registering them first prevents more specific routes from ever being reached.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKM","title":"Register FastAPI catch-all routes last","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811822+00:00","updated_at":"2026-05-03T03:52:34.811824+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Embed schema_version in each JSON line

Include `schema_version` field in every JSON line for self-describing records. Example: `{"schema_version": 1, "field": "value"}`.

**Why:** Allows schema evolution without migration code; old records missing new fields deserialize safely via Pydantic defaults.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKN","title":"Embed schema_version in each JSON line","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811831+00:00","updated_at":"2026-05-03T03:52:34.811832+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Pydantic defaults for backward-compatible schemas

Define default values in Pydantic models so records from earlier schema versions (missing new fields) deserialize without migration. Example: `new_field: str = 'default'`.

**Why:** Old JSON lacking new fields can load directly; no separate migration code needed.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKP","title":"Use Pydantic defaults for backward-compatible schemas","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811841+00:00","updated_at":"2026-05-03T03:52:34.811843+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Scan transitive dependencies when invalidating items

When invalidating a data item, recursively update all ancestors to point to final successors. Use depth limits to prevent infinite loops. Example: invalidate child → update parent → update grandparent, stop at depth limit.

**Why:** Prevents broken dependency chains in trees; loop limits protect against cycles.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKQ","title":"Scan transitive dependencies when invalidating items","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811850+00:00","updated_at":"2026-05-03T03:52:34.811852+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use atomic writes with rotate_backups for versioning

Use unconditional overwrite for small files; use atomic writes with rotation for larger ones to preserve history.

**Why:** Atomic writes prevent corruption on interruption; rotation provides natural versioning and recovery from corruption without separate backup logic.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKR","title":"Use atomic writes with rotate_backups for versioning","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811859+00:00","updated_at":"2026-05-03T03:52:34.811860+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use sha256(text)[:16] for synthetic API content IDs

When external APIs don't return content IDs, create synthetic ones using `sha256(text)[:16]`. Enables temporal tracking of content across API responses.

**Why:** Consistent hashing allows tracking whether the same content appears in different API calls or has changed.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKS","title":"Use sha256(text)[:16] for synthetic API content IDs","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811867+00:00","updated_at":"2026-05-03T03:52:34.811869+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Type signatures communicate breaking contract changes

Update function signatures to reflect stricter types (e.g., `phase: PipelineStage | Literal[""]`) before modifying callers. Existing calls with string literals continue working via StrEnum coercion; the signature is the integration point.

**Why:** Type signatures make contract changes visible to callers before implementation changes, enabling gradual adoption.

_Source: #6335 (review)_


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKT","title":"Type signatures communicate breaking contract changes","topic":null,"source_type":"review","source_issue":6335,"source_repo":null,"created_at":"2026-05-03T03:52:34.811876+00:00","updated_at":"2026-05-03T03:52:34.811877+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never import optional deps at module level in tests

Always defer optional package imports to test method level, not file-top. Wrong: `from hindsight import Bank` at top; Right: `from hindsight import Bank` inside test method.

**Why:** Module-level imports run at collection time; missing optional packages fail the entire test file, hiding all tests from the report.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKV","title":"Never import optional deps at module level in tests","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811886+00:00","updated_at":"2026-05-03T03:52:34.811887+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## External liveness watchdog is an operator-run dependency, not a factory loop

The factory process has no internal loop that notices when the process itself is down (crashed, hung, host rebooted) — a `BaseBackgroundLoop` subclass only runs while the process is alive, so it structurally cannot detect the process being dead. Issue #10009 closes this with `scripts/factory_liveness_watchdog.py`, a stdlib-only, dependency-free script (deliberately NOT importing `src/` — a watchdog that imports the thing it watches can't run when that thing is broken) that checks `/healthz` + `events.jsonl` recency and notifies (macOS `osascript`) or optionally restarts (`launchctl kickstart`, opt-in via a knob file, at most once per down-incident).

**Operator action required — this does not self-install.** Run `scripts/install_liveness_watchdog.py` once per host to render and load `~/Library/LaunchAgents/com.hydraflow.liveness.plist` (`StartInterval=300`). The factory must never invoke this installer itself: a loop cannot install the external thing whose entire purpose is watching for that loop's own process being gone. `--uninstall` removes it; both scripts accept `--dry-run` for a no-launchctl-calls preview. Complementary in-process signals (checked at the *next* boot, since nothing can watch the current one from inside itself): `StagingPromotionLoop` logs loudly if its RC cadence was missed by >1.5x `rc_cadence_hours` (`staging_promotion_loop.py::_check_missed_cadence_at_boot`), and `boot_gap_detector.py` publishes one `SYSTEM_ALERT` ("factory was down ~Xh") when `events.jsonl`'s last entry is older than `boot_gap_alert_threshold_seconds` at boot.

**Why:** A loop can only react while its own process is running; the down-detection signal for "the process itself died" must live outside the process, and the operator (not the factory) is the trust boundary for installing anything that can restart it.


```json:entry
{"id":"EXTERNAL-LIVENESS-WATCHDOG-OPERATOR-INSTALL-001","source_type":"manual","topic":"dependencies","tags":["liveness","launchd","watchdog","operator-install","issue-10009"],"rule":"The external liveness watchdog (scripts/factory_liveness_watchdog.py + scripts/install_liveness_watchdog.py) is installed manually by the operator via the installer script — the factory must never auto-install it, since a loop cannot bootstrap the external thing that watches for that loop's own process being down.","anti_pattern":"A factory loop or startup path calling scripts/install_liveness_watchdog.py automatically","code_refs":["scripts/factory_liveness_watchdog.py","scripts/install_liveness_watchdog.py","src/boot_gap_detector.py","src/staging_promotion_loop.py::_check_missed_cadence_at_boot"],"fixed_in_pr":null,"added":"2026-07-19"}
```

## Tier-1 liveness kernel is boot-correctness-aware — it never starts a stale factory

Beyond down-detection, the liveness kernel enforces **boot correctness** when installed with `--workspace` (#10734, the Tier-1 error kernel of epic #10733). It must NOT `POST /api/control/start` unless the factory's reported `boot_sha` equals `origin/<factory_branch>` HEAD **and** `commits_behind == 0` **and** the isolated workspace is checked out on the factory branch — all read from `GET /api/control/status` (`config.boot_sha`/`config.commits_behind`) plus a bounded `git fetch`/`rev-parse` of the workspace. On any *definite* mismatch it force-resyncs the workspace via `run-factory-isolated.sh` and relaunches, **pinned to `staging`** through the plist's `EnvironmentVariables` (never the shell default `main`), at most once per incident (the `stale_reboot_at` marker gate prevents a 5-minute reboot loop). This prevents the 2026-07-27 incident where a restart booted the factory 90 commits behind on `main`, idle — a "successful restart" into a stale known-good state. **Fail-closed:** an unknown git fact never authorises start and never triggers a reboot (it degrades to notify-only), so an unreadable remote cannot spin the kernel. The kernel also reaps orphaned (`ppid==1`) `pytest -n auto` workers from a dead/OOM'd build and distinguishes a wedged `credits_paused_until` from a genuine pause via `POST /api/control/credit-refresh`. The decision cores live in `scripts/liveness/` (stdlib-only, mirrors `scripts/gates/`); the never-import-`src/` contract is pinned by `tests/architecture/test_liveness_kernel_no_src_imports.py`.

**Why:** the error kernel that restarts everything else must be deterministic, LLM-free, and boring — a restart that boots stale is worse than a visible outage, because it looks healthy while doing nothing.


```json:entry
{"id":"LIVENESS-KERNEL-BOOT-CORRECTNESS-GUARD-001","source_type":"manual","topic":"dependencies","tags":["liveness","launchd","watchdog","boot-sha","staging","branch-pin","orphan-reaper","issue-10734","issue-10733"],"rule":"The Tier-1 liveness kernel must NOT POST /api/control/start unless boot_sha == origin/<factory_branch> HEAD AND commits_behind == 0 AND the workspace is on the factory branch; on any definite mismatch it force-resyncs via run-factory-isolated.sh and relaunches pinned to staging (plist EnvironmentVariables), at most once per incident. Unknown git facts are fail-closed: never start, never reboot. Decision cores in scripts/liveness/ are stdlib-only and must never import src/.","anti_pattern":"Relaunching the factory with the shell-default branch main, or issuing POST /api/control/start without first confirming boot_sha matches origin/<branch> HEAD and commits_behind==0 — booting a stale/wrong-branch factory that looks healthy while idle","code_refs":["scripts/factory_liveness_watchdog.py","scripts/liveness/boot_guard.py","scripts/liveness/orphan_reaper.py","scripts/liveness/credit_probe.py","scripts/install_liveness_watchdog.py","scripts/run-factory-isolated.sh"],"fixed_in_pr":null,"added":"2026-07-27"}
```

## Factory-as-service install recipe — launchd runs the factory in place from `~/.hydraflow`, and Stop is a latch

The factory runs as a macOS launchd agent (`com.hydraflow.factory`, ADR-0135) that executes `scripts/run-factory-isolated.sh` **in place from the dedicated workspace** `~/.hydraflow/factory-workspace/hydraflow` in SERVICE MODE (`HYDRAFLOW_FACTORY_SERVICE=1`). It must run from there, not from the dev checkout: macOS TCC denies launchd agents `~/Documents` (`make: getcwd: Operation not permitted` → `No rule to make target 'factory'`), which is how the factory sat down 15 of 31 days. Service mode replaces the launcher's dev-checkout guard with a narrower invariant — the workspace must live under `$HOME/.hydraflow/` and must already exist (the service never clones) — then runs the unchanged fetch → force-discard → reset to `origin/staging` → `make env` → `exec make run` path.

**Install recipe (operator-run, from the dev checkout; both are idempotent and accept `--dry-run`):**

```bash
python scripts/install_factory_service.py      # or: make factory-service-install
python scripts/install_liveness_watchdog.py    # com.hydraflow.liveness, StartInterval 300
```

The first clones the workspace if absent, renders `~/Library/LaunchAgents/com.hydraflow.factory.plist` (`KeepAlive` + `RunAtLoad`, `ThrottleInterval` 60, `HOME`/`PATH` pinned because launchd inherits neither, branch pinned to `staging`, logs at `~/.hydraflow/factory-launchd.{out,err}.log`), bootouts any loaded instance, writes, bootstraps. It also gives `~/.hydraflow/liveness/restart.knob` a restart target: after both installers the knob contains `RESTART_ENABLED=true` + `RESTART_LABEL=com.hydraflow.factory`, so the watchdog's `attempt_restart()` runs `launchctl kickstart -k gui/<uid>/com.hydraflow.factory` instead of logging "no RESTART_COMMAND/RESTART_LABEL configured — skipping restart". The `RESTART_LABEL` line is appended only when the knob names neither a command nor a label; existing operator keys are never overwritten. `--uninstall` removes the plist and leaves the knob alone.

**Stop means stopped.** Stop in the UI (`POST /api/control/stop`) persists the `operator_stopped` latch (#11208), and `GET /api/control/status` now exposes it (`ControlStatusResponse.operator_stopped`, factory-level in both the per-repo and `repo=__all__` responses). Both `src/factory_autostart.py` (boot-time autostart) and the liveness kernel (`scripts/liveness/boot_guard.py:decide_boot_action`) honour it: a verified-correct idle boot under the latch is NO_ACTION, never START. `POST /api/control/start` clears it. A stale stopped boot is still RESYNC_REBOOT-healed — it relaunches into the latch and stays stopped.

**Why:** a KeepAlive launchd job is the only thing on the host that restarts the factory *process* without a human; the watchdog then only needs a label to kick. And a restart kernel that cannot see the operator's Stop will undo it within one tick — the latch has to be visible at the one seam the kernel reads (`/api/control/status`), which never imports `src/`.


```json:entry
{"id":"FACTORY-AS-SERVICE-INSTALL-RECIPE-001","source_type":"manual","topic":"dependencies","tags":["launchd","factory-service","liveness","operator-stopped","latch","tcc","install-recipe","adr-0135"],"rule":"Run the factory as the com.hydraflow.factory launchd agent in place from ~/.hydraflow/factory-workspace/hydraflow via run-factory-isolated.sh SERVICE MODE (HYDRAFLOW_FACTORY_SERVICE=1; workspace must live under $HOME/.hydraflow/ and already exist). Install with scripts/install_factory_service.py then scripts/install_liveness_watchdog.py; the knob ends up RESTART_ENABLED=true + RESTART_LABEL=com.hydraflow.factory (appended only when no target is named, never overwriting operator keys). Stop in the UI sets the operator_stopped latch, exposed on GET /api/control/status and honoured by both factory_autostart and boot_guard.decide_boot_action (idle+latch -> NO_ACTION); POST /api/control/start clears it.","anti_pattern":"A launchd job (or reboot_factory) that runs the factory from a ~/Documents checkout — TCC denies it; or a liveness kernel that issues POST /api/control/start on an idle status without consulting operator_stopped, undoing a deliberate Stop within one tick; or an installer that overwrites an operator's RESTART_COMMAND/RESTART_LABEL","code_refs":["scripts/install_factory_service.py","scripts/run-factory-isolated.sh","scripts/install_liveness_watchdog.py","scripts/factory_liveness_watchdog.py","scripts/liveness/boot_guard.py","src/factory_autostart.py","src/dashboard_routes/_control_routes.py","src/models.py::ControlStatusResponse","docs/adr/0135-factory-as-launchd-service-operator-stop-latch.md"],"fixed_in_pr":null,"added":"2026-08-21"}
```
