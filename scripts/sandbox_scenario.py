"""sandbox_scenario — host-side harness for the sandbox tier.

Subcommands:
    run NAME       — Compute seed, build (if needed), boot stack, run one
                     scenario, capture artifacts, tear down.
    run-all        — Same, but iterates the catalog; produces a summary
                     table and exits nonzero if any failed.
    status         — Show current stack state without booting.
    down           — Tear down the stack and remove volumes.
    shell          — Drop into bash inside the hydraflow container.
    seed NAME      — Compute and write the JSON seed without booting.

Returns exit code 0 on full success, 1 on any scenario failure, 2 on
infrastructure failure (build / healthcheck / playwright crash).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.sandbox.yml"
SEEDS_DIR = REPO_ROOT / "tests" / "sandbox_scenarios" / "seeds"
RESULTS_DIR = Path("/tmp/sandbox-results")  # noqa: S108  # nosec B108  # Sandbox CLI artifacts dir; not a security boundary, contents are mkdir'd per-run.

# Ensure `tests.sandbox_scenarios.scenarios.*` and `mockworld.*` are
# importable when this script is invoked directly (e.g.
# `python scripts/sandbox_scenario.py`). Under pytest the rootdir +
# editable-install pth file handle this, but the CLI entrypoint doesn't
# get that for free.
for _p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def load_scenario(name: str):
    """Import a scenario module by NAME."""
    return importlib.import_module(f"tests.sandbox_scenarios.scenarios.{name}")


def write_seed(name: str, seeds_dir: Path | None = None) -> Path:
    """Compute the scenario's seed and write it into *seeds_dir*.

    *seeds_dir* defaults to the committed ``SEEDS_DIR`` — the path ``cmd_seed``
    uses to (re)generate the 6 golden seeds. ``cmd_run``/``cmd_run_all`` pass a
    throwaway temp dir instead (via ``_materialize_run_seed``) so a manual
    sandbox run of a seedless scenario never leaves an untracked ``<name>.json``
    in the source tree (#10980). Resolving ``None`` to the *module-level*
    ``SEEDS_DIR`` at call time (not a default-argument binding) keeps the
    monkeypatch-``SEEDS_DIR`` seam #10094 relies on working.
    """
    target_dir = SEEDS_DIR if seeds_dir is None else seeds_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    mod = load_scenario(name)
    out = target_dir / f"{mod.NAME}.json"
    out.write_text(mod.seed().to_json())
    return out


def _materialize_run_seed(name: str) -> Path:
    """Materialize *name*'s seed + its ``scenario.json`` symlink into a fresh
    throwaway temp dir and return that dir (#10980).

    ``cmd_run``/``cmd_run_all`` mount THIS dir at ``/seed`` (via the
    ``SANDBOX_SEED_DIR`` compose bind) instead of the committed golden
    ``SEEDS_DIR``. 72 of 78 scenarios have no committed golden seed, so writing
    into ``SEEDS_DIR`` on a manual ``run``/``run-all`` used to drop an untracked
    ``<name>.json`` (plus a ``scenario.json`` symlink) into the source tree,
    tripping ``test_seed_dir_is_git_clean`` on the next full-suite run in the
    same workspace. ``cmd_seed`` stays the only writer of the committed goldens.
    """
    seed_dir = Path(tempfile.mkdtemp(prefix="sandbox-seed-"))
    seed_path = write_seed(name, seeds_dir=seed_dir)
    # The container always reads /seed/scenario.json; point it at THIS seed.
    scenario_link = seed_dir / "scenario.json"
    scenario_link.symlink_to(seed_path.name)
    return seed_dir


def _compose(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        check=False,
        env=env,
    )


def cmd_seed(name: str) -> int:
    out = write_seed(name)
    print(f"Wrote seed: {out}")
    return 0


def cmd_down(env: dict[str, str] | None = None) -> int:
    print("Stopping stack...")
    _compose("down", "-v", env=env)
    print("Done.")
    return 0


def cmd_status() -> int:
    return _compose("ps").returncode


def cmd_shell() -> int:
    return _compose("exec", "hydraflow", "/bin/bash").returncode


def _wait_for_healthy(timeout: float = 60.0) -> bool:
    """Poll docker compose ps for hydraflow (healthy) up to timeout seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "ps",
                "--format",
                "json",
                "hydraflow",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if "(healthy)" in result.stdout or '"Health":"healthy"' in result.stdout:
            return True
        time.sleep(2)
    return False


def cmd_run(name: str) -> int:
    print(f"[1/5] Computing seed for {name}...")
    # Materialize the seed (and its scenario.json symlink) into a throwaway
    # temp dir and mount THAT at /seed, never the committed golden SEEDS_DIR —
    # otherwise a manual run of a seedless scenario pollutes the source tree
    # (#10980). SANDBOX_SEED_DIR feeds the parameterized compose bind.
    seed_dir = _materialize_run_seed(name)
    env = {**os.environ, "SANDBOX_SEED_DIR": str(seed_dir)}
    try:
        print("[2/5] Building images (cached when possible)...")
        # ``playwright`` must be built explicitly because the MS image ships no
        # test runner — ``Dockerfile.playwright`` adds pytest at build time so
        # ``compose run playwright pytest …`` works on the air-gapped network.
        rc = _compose("build", "hydraflow", "ui", "playwright", env=env).returncode
        if rc != 0:
            print(f"BUILD FAILED ({rc})")
            return 2

        print("[3/5] Starting stack on internal network...")
        rc = _compose("up", "-d", "hydraflow", "ui", env=env).returncode
        if rc != 0:
            print(f"UP FAILED ({rc})")
            return 2

        print("[4/5] Waiting for hydraflow /healthz...")
        if not _wait_for_healthy(60):
            print("HEALTHCHECK TIMEOUT — collecting logs")
            _compose("logs", "hydraflow", env=env)
            cmd_down(env=env)
            return 2

        print("[5/5] Running playwright assertions...")
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        # ``-c tests/sandbox_scenarios/pytest.ini`` makes that file the
        # rootdir-config so pytest does NOT autoload the project-wide
        # ``tests/conftest.py`` (which imports pydantic/HydraFlow internals
        # that the slim playwright image doesn't have). The runner's own
        # conftest under ``tests/sandbox_scenarios/runner/`` still loads
        # because it's inside the new rootdir.
        rc = _compose(
            "run",
            "--rm",
            "-e",
            f"SCENARIO_NAME={name}",
            "playwright",
            "pytest",
            "-c",
            "tests/sandbox_scenarios/pytest.ini",
            f"tests/sandbox_scenarios/runner/test_scenarios.py::test_scenario[{name}]",
            "-v",
            "--junitxml=/results/junit.xml",
            env=env,
        ).returncode

        if rc != 0:
            print(f"FAILED {name}")
            _compose("logs", "hydraflow", env=env)
        else:
            print(f"PASSED {name}")

        cmd_down(env=env)
        return rc
    finally:
        # The temp seed dir is single-use; never let it linger.
        shutil.rmtree(seed_dir, ignore_errors=True)


def _parse_shard(shard: str | None) -> tuple[int, int] | None:
    """Parse a ``"I/N"`` shard spec (1-indexed) into ``(index0, count)``.

    Returns ``None`` when *shard* is falsy (unsharded — run everything).
    """
    if not shard:
        return None
    i_str, sep, n_str = shard.partition("/")
    if not sep:
        raise ValueError(f"invalid --shard {shard!r}: expected I/N, e.g. 2/6")
    i, n = int(i_str), int(n_str)
    if n < 1 or not (1 <= i <= n):
        raise ValueError(f"invalid --shard {shard!r}: need 1 <= I <= N and N >= 1")
    return i - 1, n


def _select_shard(items: list, shard: str | None) -> list:
    """Return only the *shard*'s slice of *items* (round-robin stripe).

    ``items[index0::count]`` spreads adjacent (similarly-costed) scenarios
    across shards so wall-clock is balanced even when durations cluster.
    *items* must already be in a stable order (load_all_scenarios sorts by
    NAME) so every shard sees the same partition.
    """
    parsed = _parse_shard(shard)
    if parsed is None:
        return items
    index0, count = parsed
    return items[index0::count]


def _summary_payload(results: list[tuple[str, int, float]], shard: str | None) -> dict:
    """JSON-serializable run summary: which scenarios ran, and which failed.

    Consumed by the staging RC dry-run sensor (issue #10352). Each shard writes
    this file so the aggregating reporter can name the failing scenario(s)
    without scraping log output.
    """
    return {
        "shard": shard,
        "scenarios": [
            {"name": name, "rc": rc, "elapsed": round(elapsed, 2)}
            for name, rc, elapsed in results
        ],
        "failed": [name for name, rc, _ in results if rc != 0],
    }


def cmd_run_all(
    shard: str | None = None, summary_json: str | Path | None = None
) -> int:
    """Iterate every scenario; print summary; exit nonzero on any failure.

    With ``shard="I/N"`` only the I-th of N round-robin slices runs, so CI can
    fan the suite across N parallel matrix jobs.

    When ``summary_json`` is set, a machine-readable run summary (per-scenario
    name/rc + the list of failures) is written to that path *even when scenarios
    fail* — this is how the staging RC dry-run sensor (#10352) learns which
    scenario(s) broke the RC gate.
    """
    from tests.sandbox_scenarios.runner.loader import load_all_scenarios

    scenarios = [s for s in load_all_scenarios() if hasattr(s, "assert_outcome")]
    scenarios = _select_shard(scenarios, shard)
    if shard:
        print(
            f"[shard {shard}] {len(scenarios)} scenarios: "
            f"{', '.join(s.NAME for s in scenarios)}"
        )
    results: list[tuple[str, int, float]] = []
    for s in scenarios:
        start = time.monotonic()
        rc = cmd_run(s.NAME)
        elapsed = time.monotonic() - start
        results.append((s.NAME, rc, elapsed))

    if summary_json is not None:
        Path(summary_json).write_text(
            json.dumps(_summary_payload(results, shard), indent=2)
        )

    print("\n--- Summary ---")
    fails = 0
    for name, rc, elapsed in results:
        status = "PASSED" if rc == 0 else "FAILED"
        if rc != 0:
            fails += 1
        print(f"{status:8s} {name:40s} ({elapsed:5.1f}s)")
    print(f"\n{len(results) - fails} passed, {fails} failed")
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sandbox_scenario")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("down")
    sub.add_parser("shell")
    p_all = sub.add_parser("run-all")
    p_all.add_argument(
        "--shard",
        default=None,
        help="Run only shard I of N (1-indexed, round-robin), e.g. --shard 2/6",
    )
    p_all.add_argument(
        "--summary-json",
        default=None,
        help=(
            "Write a JSON run summary (per-scenario name/rc + failures) to PATH. "
            "Used by the staging RC dry-run sensor (#10352) to name broken "
            "scenarios."
        ),
    )
    p_run = sub.add_parser("run")
    p_run.add_argument("name")
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("name")

    args = parser.parse_args()
    if args.cmd == "run-all":
        return cmd_run_all(shard=args.shard, summary_json=args.summary_json)
    nullary = {
        "status": cmd_status,
        "down": cmd_down,
        "shell": cmd_shell,
    }
    unary = {
        "run": cmd_run,
        "seed": cmd_seed,
    }
    if args.cmd in nullary:
        return nullary[args.cmd]()
    if args.cmd in unary:
        return unary[args.cmd](args.name)
    return 2


if __name__ == "__main__":
    sys.exit(main())
