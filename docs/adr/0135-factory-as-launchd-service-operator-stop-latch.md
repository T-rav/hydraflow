# ADR-0135: Factory runs as a launchd service; operator Stop is a latch honoured by autostart and the liveness kernel

- **Status:** Accepted
- **Date:** 2026-08-21
- **Enforcement:** enforced
- **Binds:** factory
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0042](0042-two-tier-branch-release-promotion.md) (the factory runs on `staging`; the service pins that branch), [ADR-0029](0029-caretaker-loop-pattern.md) (why the restart kernel lives *outside* the process)

**Enforced by:**
pytest:tests/test_factory_launcher_service_mode.py::test_service_mode_refuses_workspace_outside_dot_hydraflow
pytest:tests/test_factory_launcher_service_mode.py::test_service_mode_refuses_missing_workspace_instead_of_cloning
pytest:tests/test_install_factory_service.py::TestRenderPlist::test_environment_pins_service_mode_workspace_branch_home_and_path
pytest:tests/test_install_factory_service.py::TestEnsureRestartLabel::test_never_overwrites_an_existing_label
pytest:tests/test_liveness_boot_guard.py::TestOperatorStoppedLatch::test_idle_verified_boot_under_latch_is_no_action_not_start
pytest:tests/test_operator_stopped_latch_routes.py::test_status_carries_operator_stopped_after_stop_and_clears_after_start
pytest:tests/regressions/test_liveness_kernel_operator_stop_latch.py
pytest:tests/scenarios/test_operator_stop_latch_kernel_scenario.py

## Context

The factory was down 15 of the last 31 days. Its launchd autostart failed with
`make: getcwd: Operation not permitted` / `No rule to make target 'factory'`:
the job ran from `~/Documents`, which macOS TCC denies to launchd agents. The
dedicated workspace (`~/.hydraflow/factory-workspace/hydraflow`) is outside
TCC, but `scripts/run-factory-isolated.sh` refused to run *from* it — its
"never `reset --hard` the dev checkout" guard aborts when `DEV_ROOT ==
WORKSPACE` — so neither a launchd job nor the liveness kernel's
`reboot_factory()` (whose `_LAUNCHER_SCRIPT` is its own repo root) could
relaunch the factory without a `~/Documents` checkout in the loop.

Two further gaps surfaced once the kernel was armed with `--workspace`:

1. `scripts/liveness/boot_guard.py` issues `POST /api/control/start` whenever
   `/api/control/status` reports `idle`/`done` on a verified-correct boot. After
   `POST /api/control/stop` the orchestrator is gone and status reads `idle` —
   indistinguishable from a never-started boot — and the persisted
   `operator_stopped` latch (#11208) was not exposed at all. An operator's Stop
   was therefore undone within one 5-minute tick. `src/factory_autostart.py`
   already honoured the latch; the kernel did not.
2. `~/.hydraflow/liveness/restart.knob` as seeded by
   `scripts/install_liveness_watchdog.py` contains only `RESTART_ENABLED=true`,
   so `attempt_restart()` logged "no RESTART_COMMAND/RESTART_LABEL configured —
   skipping restart". The watchdog could notice the factory was down but had
   nothing to kick.

## Decision

1. **The factory runs as a macOS launchd service, in place from its own
   workspace.** `scripts/install_factory_service.py` renders
   `~/Library/LaunchAgents/com.hydraflow.factory.plist` whose job is
   `/bin/bash <workspace>/scripts/run-factory-isolated.sh` with
   `WorkingDirectory` = the workspace, `KeepAlive` + `RunAtLoad`,
   `ThrottleInterval` 60, and explicit `HOME`/`PATH` (launchd agents inherit
   neither a login profile nor Homebrew's bin). Branch is pinned to `staging`
   (ADR-0042) via `EnvironmentVariables`. The installer is operator-run from
   the dev checkout (never by the factory itself — the same trust boundary as
   the liveness watchdog) and is the only path that clones the workspace.
2. **`run-factory-isolated.sh` gains an explicit SERVICE MODE**
   (`HYDRAFLOW_FACTORY_SERVICE=1`). It replaces the dev-checkout guard with a
   *narrower* invariant rather than weakening it: the resolved workspace must
   live under `$HOME/.hydraflow/` and must already exist; the origin URL comes
   from the workspace's own remote; the `.env` copy is skipped (the workspace's
   gitignored `.env` is the one in use); the fetch → force-discard → reset →
   `make env` → `exec make run` path runs unchanged. The non-service path and
   every existing guard are untouched.
3. **Operator Stop is a latch that *both* autostart and the liveness kernel
   honour.** `ControlStatusResponse.operator_stopped` (`src/models.py`) exposes
   `StateData.operator_stopped` on `GET /api/control/status`
   (`src/dashboard_routes/_control_routes.py`), in the per-repo response and
   the `repo=__all__` rollup alike — the latch is factory-level (Stop halts
   every line and latches the host state), so both report that one host
   latch. `scripts/liveness/boot_guard.py:decide_boot_action` turns a would-be
   START under the latch into NO_ACTION (`notify=False`: a deliberate Stop is
   not an incident). RESYNC_REBOOT is unchanged — a stale boot is still
   healed, relaunches into the latch, and stays stopped. The field is read
   fail-open (missing/non-bool → `False`) so a factory that predates it keeps
   the prior behaviour. `scripts/liveness/` stays stdlib-only.
4. **The liveness knob gets a restart target.** The installer appends
   `RESTART_LABEL=com.hydraflow.factory` to `restart.knob` only when it names
   neither `RESTART_COMMAND` nor `RESTART_LABEL`; existing operator keys are
   never overwritten (the `seed_restart_knob` contract). `--uninstall` leaves
   the knob alone.

## Consequences

- `python scripts/install_factory_service.py` then
  `python scripts/install_liveness_watchdog.py` is the full install recipe
  (wiki: "Factory-as-service install recipe"). launchd keeps the factory
  process up; the watchdog heals stale boots and kicks the label when the
  process is dead; `factory_autostart` brings the host line up on boot.
- Stop in the UI means stopped: neither boot-time autostart nor the external
  kernel will restart the host line until `POST /api/control/start` clears
  the latch. The kernel *does* still resync a stale stopped boot — it boots
  into the latch.
- Service mode is opt-in by env and refused anywhere outside
  `$HOME/.hydraflow/`, so the in-place `reset --hard` can never reach a
  developer's checkout.
- launchd cannot run inside docker: the sandbox e2e tier covers the control
  routes and the kernel decision, not the service itself.
- Linux hosts are out of scope here (the installer exits 1); a systemd unit
  would invoke the same service-mode launcher.
