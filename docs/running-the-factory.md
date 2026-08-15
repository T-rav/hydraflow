# Running the factory without dirtying your checkout

The factory mutates the directory it runs from (`config.repo_root`): the wiki,
arch, and runtime-cache loops write artifacts into the working tree as they
operate, and each maintenance PR is built in an *ephemeral* worktree
(`auto_pr.open_automated_pr_async`) that never cleans the originals. If you run
`make run` from the same checkout you develop in, that checkout is permanently
dirty.

## Use a dedicated workspace

```bash
make factory
```

This runs `scripts/run-factory-isolated.sh`, which:

1. Clones the repo (once) into a dedicated workspace —
   `~/.hydraflow/factory-workspace/hydraflow` by default.
2. Hard-syncs that workspace to the latest base branch (`staging` by default —
   ADR-0042 two-tier model; `main` advances only via RC promotion) on every
   launch — the workspace is the factory's scratch space, so its churn is
   discarded here.
3. Copies your dev checkout's `.env` into the workspace so credentials/config
   carry over.
4. Launches the server (`make run`) from the workspace.

Your dev checkout is never touched. The factory's PRs still land on `origin` as
usual; pull them into your clean checkout with `git pull`.

### Overrides

| Env var | Default | Purpose |
|---|---|---|
| `HYDRAFLOW_FACTORY_WORKSPACE` | `~/.hydraflow/factory-workspace/hydraflow` | Where the dedicated clone lives |
| `HYDRAFLOW_FACTORY_BRANCH` | `staging` | Branch the factory runs (ADR-0042; `main` only via RC promotion) |

## Autostart: server-up now means factory-running

`make factory` (and every unattended relaunch — stale-code heal, OOM
recovery, reboot) used to only bring up the dashboard/server; the runtime
booted `running:false` until someone remembered `POST /api/control/start`.
`server.py`'s boot sequence now fires that same call automatically once the
dashboard is healthy (`src/factory_autostart.py`), so a fresh boot goes
straight to working instead of sitting idle.

Two things suppress it, both intentional:

| Suppressor | Where it lives | Effect |
|---|---|---|
| `factory_autostart` config flag (`HYDRAFLOW_FACTORY_AUTOSTART`, default `true`) | `HydraFlowConfig` | Set `false` to boot idle every time, e.g. for a debug session where you want to inspect state before pressing Play. |
| Operator-stopped latch (`state.operator_stopped`) | persisted `state.json` | Set the moment an operator hits `POST /api/control/stop`; cleared on the next `POST /api/control/start`. A deliberate Stop survives relaunch — autostart never resurrects a factory the operator explicitly took down. |

An active credit pause is not a suppressor: autostart fires the identical
`host_runtime.start()` call `POST /api/control/start` makes, so if the
account is still exhausted the orchestrator's own credit-exhaustion detection
re-pauses it on the first spawn — the factory boots *into* the pause, not
past it.

MockWorld and the sandbox docker entrypoint (`mockworld/sandbox_main.py`)
never autostart — both boot a `HydraFlowDashboard` directly and never import
`factory_autostart`, so the guarantee is structural, not a runtime flag
(enforced by `tests/architecture/test_factory_autostart_confinement.py`).

## Boot-correctness: the liveness kernel never starts a stale factory

The launchd liveness kernel (`scripts/factory_liveness_watchdog.py`, agent
`com.hydraflow.liveness`, installed by `scripts/install_liveness_watchdog.py`) is
the Tier-1 error kernel that keeps the factory running (#10734). Beyond the
`/healthz` + `events.jsonl` down-detection, when installed with `--workspace` it
**refuses to `POST /api/control/start` onto a stale boot**: unless the factory's
reported `boot_sha` equals `origin/<factory_branch>` HEAD **and** `commits_behind`
is `0` **and** the workspace is on the factory branch, it force-resyncs the
isolated workspace (`run-factory-isolated.sh`'s `fetch → checkout -f → reset
--hard → clean -fd`) and relaunches — pinned to `staging` via the plist's
`EnvironmentVariables` — instead of booting stale. This prevents the 2026-07-27
incident where a restart booted the factory 90 commits behind on `main`, idle.
It also reaps orphaned `pytest -n auto` workers from a dead/OOM'd build and
probes a wedged `credits_paused_until`. It is deterministic, LLM-free, and
stdlib-only.

The kernel's own `START` action (`decide_boot_action`) now overlaps with
server-boot autostart above — both end up calling `POST /api/control/start`
on a healthy, verified-correct boot. That's fine: `host_runtime.start()` is a
no-op when the line is already running, so whichever one gets there first
wins and the other is a harmless idempotent check.

## Why not just `git restore` after each run?

The runtime caches (`docs/wiki/log.jsonl`, `ingest_dedup.json`, `index.json`)
are now gitignored, and the maintenance loops will be taught to self-clean after
their PR merges — but isolating the workspace is the robust catch-all: a fresh
writer that forgets to clean up can't dirty a checkout it never touches.
