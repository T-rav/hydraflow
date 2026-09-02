"""Startup dependency health checks for HydraFlow."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from config import HydraFlowConfig, _detect_repo_slug, _dotenv_lookup

logger = logging.getLogger("hydraflow.preflight")

# `gh auth status` can take 5-10s on first invocation when the OS keychain
# unlocks the token. Bounded so a stuck process can't block startup forever
# (#6576). Module-level so tests can patch a smaller value.
_GH_AUTH_TIMEOUT_S = 15.0


class CheckStatus(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str


async def run_preflight_checks(config: HydraFlowConfig) -> list[CheckResult]:
    """Run all preflight checks and return results."""
    results: list[CheckResult] = []
    results.append(_check_git())
    results.append(_check_gh_cli())
    results.append(await _check_gh_auth())
    results.append(_check_repo_root(config.repo_root))
    results.append(_check_pipeline_target(config))
    results.append(_check_disk_space(config.data_root))
    if config.execution_mode == "docker":
        results.append(_check_docker())
        results.append(_check_docker_agent_credential(config))
    # Check configured agent CLIs
    for tool_field in ("implementation_tool", "review_tool", "planner_tool"):
        tool = getattr(config, tool_field)
        if tool != "inherit":
            results.append(_check_agent_cli(tool))

    # Plugin skill registry — verify required plugins are installed.
    # Language detection runs per-repo later; at preflight we only check Tier 1.
    results.append(_check_plugins(config, detected_languages=set()))

    # Strays from a PREVIOUS run, found before this one starts competing
    # with them for the same CPU (#11820).
    results.append(_check_stray_quality_processes(config))
    # A leaked factory matches none of the suite markers above, so it needs its
    # own structural check — three trees survived 21h undetected (#11840).
    results.append(_check_abandoned_factory_trees(config))
    results.append(_check_contracts_sandbox(config))

    return results


#: Either credential lets a containerized claude worker authenticate; the
#: resolution order (process env, then repo_root/.env) mirrors
#: subprocess_util.make_docker_env, which is what actually feeds the container.
_CLAUDE_CREDENTIAL_KEYS: tuple[str, ...] = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
)

#: The three dispatching roles preflight already checks CLIs for, paired with
#: the provider dial that exempts them: a role resolved to the gateway gets a
#: per-spawn virtual key, never a host credential — and under
#: gateway_fleet_ratchet_enabled the dials are promoted to "gateway" during
#: config resolution, before preflight ever sees them.
_CLAUDE_ROLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("implementation_tool", "implementation_provider"),
    ("review_tool", "review_provider"),
    ("planner_tool", "planner_provider"),
)


def _check_pipeline_target(config: HydraFlowConfig) -> CheckResult:
    """WARN when no repo is targeted — the factory otherwise idles silently.

    WARN rather than FAIL: booting untargeted and registering repos through
    the dashboard afterwards is a legal path. But the consequence belongs in
    the preflight report the operator reads, not only in an import-time
    ``logger.warning`` inside a pydantic validator (#12040).
    """
    if config.repo:
        return CheckResult(
            "pipeline-target", CheckStatus.PASS, f"pipeline target: {config.repo}"
        )
    detected = _detect_repo_slug(config.repo_root)
    remote_note = (
        f" (The checkout's own remote is {detected!r}; it is never targeted"
        " automatically.)"
        if detected
        else ""
    )
    return CheckResult(
        "pipeline-target",
        CheckStatus.WARN,
        "HYDRAFLOW_GITHUB_REPO is unset — the triage/plan/implement/review "
        "loops will idle. Set HYDRAFLOW_GITHUB_REPO=<owner>/<repo> or register "
        f"a repo via the dashboard.{remote_note}",
    )


def _check_docker_agent_credential(config: HydraFlowConfig) -> CheckResult:
    """FAIL when docker mode dispatches direct-claude workers with no credential.

    Containers cannot reach the host keychain, so a host-mode login does not
    travel; unlike an unset repo there is no post-boot UI path that fixes
    this, and every dispatched claude worker fails mid-run with the
    "Agent CLI authentication failed" string in ``runner_utils`` (#12040).
    """
    direct_claude_roles = [
        tool_field
        for tool_field, provider_field in _CLAUDE_ROLE_FIELDS
        if getattr(config, tool_field) == "claude"
        and getattr(config, provider_field) != "gateway"
    ]
    if not direct_claude_roles:
        return CheckResult(
            "docker-agent-credential",
            CheckStatus.PASS,
            "no direct-claude roles configured — no host claude credential needed",
        )
    for key in _CLAUDE_CREDENTIAL_KEYS:
        if os.environ.get(key, "") or _dotenv_lookup(config.repo_root, key):
            return CheckResult(
                "docker-agent-credential",
                CheckStatus.PASS,
                f"{key} present for docker-mode claude workers "
                f"({', '.join(direct_claude_roles)})",
            )
    return CheckResult(
        "docker-agent-credential",
        CheckStatus.FAIL,
        "docker mode dispatches claude workers ("
        + ", ".join(direct_claude_roles)
        + ") but neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set "
        "in the environment or .env — containers cannot reach the host "
        "keychain. Run 'claude setup-token' and put the token in .env.",
    )


def _check_git() -> CheckResult:
    """Check that git is available on PATH."""
    if shutil.which("git"):
        return CheckResult("git", CheckStatus.PASS, "git found on PATH")
    return CheckResult("git", CheckStatus.FAIL, "git not found on PATH")


def _check_gh_cli() -> CheckResult:
    """Check that the GitHub CLI is available on PATH."""
    if shutil.which("gh"):
        return CheckResult("gh-cli", CheckStatus.PASS, "gh CLI found on PATH")
    return CheckResult("gh-cli", CheckStatus.FAIL, "gh CLI not found on PATH")


async def _check_gh_auth() -> CheckResult:
    """Check that gh CLI is authenticated."""
    if not shutil.which("gh"):
        return CheckResult(
            "gh-auth", CheckStatus.FAIL, "gh CLI not found — cannot check auth"
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "auth",
            "status",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            # Timeout WARNs (not FAILs) so a slow keychain doesn't block
            # startup; downstream gh calls do their own auth handling. The
            # process is killed on timeout to avoid orphans (#6576).
            rc = await asyncio.wait_for(proc.wait(), timeout=_GH_AUTH_TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            return CheckResult(
                "gh-auth",
                CheckStatus.WARN,
                f"gh auth status did not complete within {_GH_AUTH_TIMEOUT_S:g}s — gh CLI appears hung; skipping auth verification",
            )
        if rc == 0:
            return CheckResult("gh-auth", CheckStatus.PASS, "gh CLI authenticated")
        return CheckResult(
            "gh-auth",
            CheckStatus.FAIL,
            "gh CLI not authenticated (run 'gh auth login')",
        )
    except OSError as exc:
        return CheckResult("gh-auth", CheckStatus.FAIL, f"gh auth check failed: {exc}")


def _check_repo_root(path: Path) -> CheckResult:
    """Check that repo_root exists and contains a .git directory."""
    if not path.exists():
        return CheckResult(
            "repo-root", CheckStatus.FAIL, f"repo_root does not exist: {path}"
        )
    if not (path / ".git").exists():
        return CheckResult(
            "repo-root", CheckStatus.WARN, f"repo_root has no .git directory: {path}"
        )
    return CheckResult("repo-root", CheckStatus.PASS, f"repo_root valid: {path}")


def _check_disk_space(path: Path) -> CheckResult:
    """Warn if less than 1 GB free disk space at the given path."""
    try:
        resolved = path if path.exists() else path.parent
        # Walk up to find an existing ancestor
        while not resolved.exists() and resolved != resolved.parent:
            resolved = resolved.parent
        usage = shutil.disk_usage(resolved)
        free_gb = usage.free / (1024**3)
        if free_gb < 1.0:
            return CheckResult(
                "disk-space",
                CheckStatus.WARN,
                f"Low disk space: {free_gb:.2f} GB free at {path}",
            )
        return CheckResult(
            "disk-space",
            CheckStatus.PASS,
            f"{free_gb:.1f} GB free at {path}",
        )
    except OSError as exc:
        return CheckResult(
            "disk-space", CheckStatus.WARN, f"Could not check disk space: {exc}"
        )


#: A `make quality` run far past the suite's own budget is not slow, it is
#: abandoned. The suite's own per-test cap is 300s and a full run is ~10-15
#: minutes; an hour is well beyond anything a live run reaches.
STRAY_PROCESS_AGE_SECONDS = 3600

#: Command substrings that identify a heavyweight suite run. Deliberately
#: narrow: this check only ever REPORTS, but a wide pattern would report an
#: operator's own editor or shell and train everyone to ignore it.
_STRAY_MARKERS = ("make quality", "make quality-unlocked", "pytest tests/")


def _stray_process_lines(ps_output: str, *, min_age_seconds: int) -> list[str]:
    """Rows from ``ps -eo pid,etime,command`` that look abandoned.

    Pure so it can be tested against recorded output — the alternative is a
    check that only runs on a host that already has the bug.

    ``etime`` is ``[[DD-]HH:]MM:SS``. A row is stray when it names a suite run
    AND has outlived :data:`STRAY_PROCESS_AGE_SECONDS`.
    """
    stray: list[str] = []
    for line in ps_output.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        _pid, etime, command = parts
        if not any(marker in command for marker in _STRAY_MARKERS):
            continue
        if _etime_seconds(etime) >= min_age_seconds:
            stray.append(f"{_pid} ({etime}) {command[:90]}")
    return stray


#: A `make factory` process group has one job: supervise `python -m server`.
#: When that server is gone the group is abandoned however young it is, so this
#: check keys on structure and never on age — a healthy factory runs for days,
#: and an age rule would flag the working one forever (#11840).
#:
#: Both patterns anchor to the EXECUTABLE. On a host running LLM agents `ps` is
#: full of processes *talking about* these commands: the factory's own triage
#: agent carries "make factory" inside its prompt, and a monitoring shell
#: carries it in its own command line. Matching the phrase anywhere would point
#: an operator at live factory work. Measured 2026-08-30, a substring count of
#: "python -m server" gave 2 for an abandoned tree and 4 for a healthy one —
#: both non-zero, so it cannot separate them at all.
_FACTORY_LEADER_RE = re.compile(r"/make\s+factory(\s|$)")
_FACTORY_SERVER_RE = re.compile(r"/python[0-9.]*\s+-m\s+server(\s|$)")


def _abandoned_factory_groups(ps_output: str) -> list[str]:
    """PGIDs of `make factory` groups that have lost their server (#11840).

    Takes ``ps -eo pgid,pid,etime,command``. Pure, so the three-way fixture in
    ``tests/regressions/test_issue_11840_abandoned_factory_trees.py`` can pin
    healthy / abandoned / decoy without needing a host that has the bug.
    """
    leaders: set[str] = set()
    served: set[str] = set()
    for line in ps_output.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pgid, _pid, _etime, command = parts
        if _FACTORY_LEADER_RE.search(command):
            leaders.add(pgid)
        if _FACTORY_SERVER_RE.search(command):
            served.add(pgid)
    return sorted(leaders - served)


def _etime_seconds(etime: str) -> int:
    """Parse ps ELAPSED (``[[DD-]HH:]MM:SS``) into seconds; 0 if unparseable."""
    days = 0
    rest = etime
    if "-" in etime:
        day_part, _, rest = etime.partition("-")
        if not day_part.isdigit():
            return 0
        days = int(day_part)
    bits = rest.split(":")
    if not all(b.isdigit() for b in bits) or not 2 <= len(bits) <= 3:
        return 0
    nums = [int(b) for b in bits]
    hours, minutes, seconds = ([0] + nums)[-3:] if len(nums) == 2 else nums
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


def _check_contracts_sandbox(config: HydraFlowConfig) -> CheckResult:
    """The contracts sandbox repo must exist while external recording is on.

    `ContractRefreshLoop` re-records FakeGitHub cassettes against
    `config.contracts_sandbox_repo`. When that repo does not exist the loop
    degrades gracefully — `if main_sha is None: return None` — so it completes,
    the factory reports healthy, and the only trace is a warning per cycle.

    Measured 2026-08-30: `T-rav-Hydra-Ops/hydraflow-contracts-sandbox` returns
    404 and had been doing so long enough that six `gh: Not Found` warnings in
    one run read as background noise. A permanent condition wearing a transient
    failure's clothes — the same shape as the wiki-compilation burn (#11819),
    where a swallowed warning cost six hours before anyone looked.

    Reported at boot instead, ONCE, where an operator is already reading. A
    recurring mid-run warning is the one thing guaranteed to be tuned out.
    """
    if not getattr(config, "contract_refresh_external_enabled", False):
        return CheckResult(
            "contracts-sandbox",
            CheckStatus.PASS,
            "external contract recording disabled; sandbox repo not required",
        )

    slug = getattr(config, "contracts_sandbox_repo", "") or ""
    # #11837 — the github recorder is skipped while its target is the shipped
    # placeholder, so on a stock install there is nothing here to warn about
    # and the docker/claude recorders keep working. Reporting "unreachable"
    # for a recorder that is not running would be the same class of misleading
    # signal this check was written to remove.
    placeholder = HydraFlowConfig.model_fields["contracts_sandbox_repo"].default
    if slug == placeholder:
        return CheckResult(
            "contracts-sandbox",
            CheckStatus.PASS,
            f"contracts_sandbox_repo is still the placeholder {slug!r}, so the "
            "github recorder is skipped; docker and claude still record. Point "
            "it at a real repo to enable github contract recording.",
        )
    if not slug:
        return CheckResult(
            "contracts-sandbox",
            CheckStatus.WARN,
            "external contract recording is ON but contracts_sandbox_repo is empty",
        )

    result = _run_fixed_argv(
        ["gh", "api", f"repos/{slug}", "--jq", ".full_name"], timeout=20, text=True
    )
    if result is None:
        return CheckResult(
            "contracts-sandbox",
            CheckStatus.WARN,
            f"could not reach GitHub to check {slug}",
        )
    if result.returncode == 0:
        return CheckResult("contracts-sandbox", CheckStatus.PASS, f"{slug} reachable")
    return CheckResult(
        "contracts-sandbox",
        CheckStatus.WARN,
        f"contracts sandbox {slug!r} is unreachable, so ContractRefreshLoop's "
        "github recorder can never re-record cassettes — it will warn every "
        "cycle and never succeed (#11821). Create the repo, or repoint "
        "`contracts_sandbox_repo` (its placeholder default skips the github "
        "recorder outright). Dropping `github` from "
        "`contract_refresh_external_recorders` silences just this recorder; "
        "`contract_refresh_external_enabled=false` also stops docker and "
        "claude, which is more than this problem calls for (#11837).",
    )


def _check_abandoned_factory_trees(config: HydraFlowConfig) -> CheckResult:
    """Report `make factory` groups whose server is gone (#11840).

    Measured 2026-08-30: three trees from 00:35, 00:37 and 00:38 were alive at
    21:30 — 24 processes holding ports 5556-5558, each running a vite watcher
    with no server left to serve. `_check_stray_quality_processes` reported PASS
    throughout, because a leaked factory matches none of its markers.

    Reports only, like its sibling: signalling processes from a preflight check
    is how a shared host loses someone's work, and one of the decoys this
    predicate had to learn to exclude was the factory's own live triage agent.
    """
    del config  # host-wide by nature
    result = _run_fixed_argv(
        ["ps", "-eo", "pgid,pid,etime,command"], timeout=15, text=True
    )
    if result is None:
        return CheckResult(
            "abandoned-factory", CheckStatus.WARN, "could not enumerate processes"
        )
    if result.returncode != 0:
        return CheckResult(
            "abandoned-factory", CheckStatus.WARN, "ps exited non-zero; skipped"
        )

    groups = _abandoned_factory_groups(result.stdout)
    if not groups:
        return CheckResult(
            "abandoned-factory",
            CheckStatus.PASS,
            "no abandoned factory trees on this host",
        )
    listed = ", ".join(groups[:5])
    return CheckResult(
        "abandoned-factory",
        CheckStatus.WARN,
        f"{len(groups)} `make factory` group(s) have no running server and are "
        f"abandoned (#11840): pgid {listed}. Each still holds a UI dev server "
        "and a port. Confirm with `ps -eo pgid,pid,command | awk '$1==<pgid>'`, "
        "then stop by process group (`kill -TERM -<pgid>`) — never `pkill -f`, "
        "which matches agents whose prompts mention these commands.",
    )


def _check_stray_quality_processes(config: HydraFlowConfig) -> CheckResult:
    """Report suite runs left over from a previous cycle (#11820).

    Measured 2026-08-30: a `make quality` from a factory build survived the
    factory's own stop, ran for **11h53m** at ``PPID=1`` holding 2.4 GB, and
    drove load average to 25. A fresh `make quality` on that host produced 60
    failures across dozens of unrelated files — every one passing standalone,
    thin enough to read as flakiness rather than starvation.

    So this reports before the new run starts competing with the old one. It
    does not kill anything: signalling processes at startup is how a shared
    host loses an operator's work, and the safe action here is to be LOUD.
    """
    del config  # host-wide by nature; nothing repo-scoped to consult
    result = _run_fixed_argv(["ps", "-eo", "pid,etime,command"], timeout=15, text=True)
    if result is None:
        return CheckResult(
            "stray-quality", CheckStatus.WARN, "could not enumerate processes"
        )
    if result.returncode != 0:
        return CheckResult(
            "stray-quality", CheckStatus.WARN, "ps exited non-zero; skipped"
        )

    stray = _stray_process_lines(
        result.stdout, min_age_seconds=STRAY_PROCESS_AGE_SECONDS
    )
    if not stray:
        return CheckResult(
            "stray-quality", CheckStatus.PASS, "no abandoned suite runs on this host"
        )
    listed = "; ".join(stray[:5])
    return CheckResult(
        "stray-quality",
        CheckStatus.WARN,
        f"{len(stray)} suite run(s) older than "
        f"{STRAY_PROCESS_AGE_SECONDS // 3600}h still running — they will "
        f"starve this run and can fail unrelated tests (#11820): {listed}. "
        "Stop them by PID (never `pkill -f` on a shared host).",
    )


def _run_fixed_argv(
    argv: list[str], *, timeout: int, text: bool = False
) -> subprocess.CompletedProcess[Any] | None:
    """Run a FIXED argv for a preflight probe; ``None`` if it could not run.

    One place in this module invokes a subprocess, so one suppression covers
    it. Each caller adding its own bandit suppression grows the suppressions
    ratchet, and that ratchet only shrinks — the `ps` sweep (#11820) hit
    exactly that.

    ``argv`` is always a literal list built in this file. Nothing here is
    caller-supplied, which is why the rule is suppressed rather than the input
    sanitised: there is no input.
    """
    try:
        return subprocess.run(  # noqa: S603, S607
            argv,
            check=False,
            capture_output=True,
            text=text,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _check_docker() -> CheckResult:
    """Check that Docker is available and responsive."""
    if not shutil.which("docker"):
        return CheckResult("docker", CheckStatus.FAIL, "docker not found on PATH")

    result = _run_fixed_argv(["docker", "info"], timeout=10)
    if result is None:
        return CheckResult("docker", CheckStatus.FAIL, "Docker check could not run")
    if result.returncode == 0:
        return CheckResult("docker", CheckStatus.PASS, "Docker daemon reachable")
    return CheckResult("docker", CheckStatus.FAIL, "Docker daemon not reachable")


def _check_agent_cli(tool: str) -> CheckResult:
    """Check that the agent CLI binary is on PATH."""
    binary = tool  # claude, codex, pi — the binary name matches the tool name
    if shutil.which(binary):
        return CheckResult(
            f"agent-cli-{tool}", CheckStatus.PASS, f"{binary} found on PATH"
        )
    return CheckResult(
        f"agent-cli-{tool}",
        CheckStatus.WARN,
        f"{binary} not found on PATH (needed for {tool} tool)",
    )


def log_preflight_results(results: list[CheckResult]) -> bool:
    """Log each preflight result and return True if no FAIL results."""
    for r in results:
        if r.status == CheckStatus.PASS:
            logger.info("[PASS] %s — %s", r.name, r.message)
        elif r.status == CheckStatus.WARN:
            logger.warning("[WARN] %s — %s", r.name, r.message)
        else:
            logger.error("[FAIL] %s — %s", r.name, r.message)
    return not any(r.status == CheckStatus.FAIL for r in results)


def install_plugin(
    name: str, marketplace: str, *, timeout_s: int = 120
) -> tuple[bool, str]:
    """Attempt ``claude plugin install name@marketplace --scope user``.

    Returns ``(success, detail)`` where ``detail`` is the tail of stderr
    (or a human-readable error string) for logging.
    """

    argv = [
        "claude",
        "plugin",
        "install",
        f"{name}@{marketplace}",
        "--scope",
        "user",
    ]
    try:
        result = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return False, "`claude` binary not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"install timed out after {timeout_s}s"

    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, (result.stderr or result.stdout or "non-zero exit").strip()


def _check_plugins(  # noqa: PLR0911 — linear gate checks, each with its own return path
    config: HydraFlowConfig,
    *,
    cache_root: Path | None = None,
    detected_languages: set[str] | None = None,
) -> CheckResult:
    """Verify required plugins are installed under the plugin cache.

    - Tier 1 (``config.required_plugins``) missing → attempt auto-install when
      ``config.auto_install_plugins`` is True; otherwise FAIL immediately. FAIL
      with a rich error message if still missing after install.
    - Zero total skills discovered → FAIL.
    - Tier 2 plugin missing for a detected language → best-effort install, then
      WARN if still missing.
    - Everything present → PASS.
    """
    from plugin_skill_registry import (
        default_cache_root,  # noqa: PLC0415
        discover_plugin_skills,  # noqa: PLC0415
        parse_plugin_spec,  # noqa: PLC0415
    )

    root = cache_root or default_cache_root()
    langs = detected_languages or set()

    if root.exists() and not root.is_dir():
        return CheckResult(
            "plugins",
            CheckStatus.FAIL,
            f"Plugin cache path exists but is not a directory: {root}",
        )

    # Collect Tier-1 + Tier-2 specs.
    tier1_specs: list[tuple[str, str]] = []
    for entry in config.required_plugins:
        try:
            tier1_specs.append(parse_plugin_spec(entry))
        except ValueError as exc:
            return CheckResult(
                "plugins", CheckStatus.FAIL, f"Bad required_plugins entry: {exc}"
            )

    tier2_specs: list[tuple[str, str, str]] = []  # (lang, name, marketplace)
    for lang in langs:
        for entry in config.language_plugins.get(lang, []):
            try:
                name, marketplace = parse_plugin_spec(entry)
            except ValueError as exc:
                return CheckResult(
                    "plugins", CheckStatus.FAIL, f"Bad language_plugins entry: {exc}"
                )
            tier2_specs.append((lang, name, marketplace))

    # Identify missing Tier-1 before any install attempt.
    missing_tier1 = [(n, m) for n, m in tier1_specs if not plugin_exists(root, n)]

    install_errors: list[str] = []
    if missing_tier1 and config.auto_install_plugins:
        for name, marketplace in missing_tier1:
            ok, detail = install_plugin(name, marketplace)
            if ok:
                logger.info("installed %s@%s", name, marketplace)
            else:
                install_errors.append(f"{name}@{marketplace}: {detail}")

    # Re-check after install attempt.
    still_missing = [(n, m) for n, m in tier1_specs if not plugin_exists(root, n)]
    if still_missing:
        pretty = ", ".join(f"{n}@{m}" for n, m in still_missing)
        if config.auto_install_plugins:
            header = f"Plugin install failed for: {pretty}"
            errors_block = (
                "\n".join(f"  {e}" for e in install_errors)
                or "  (no install errors captured)"
            )
            middle = f"Last errors:\n{errors_block}\n"
        else:
            header = f"Required plugins missing: {pretty}"
            middle = "Auto-install disabled (auto_install_plugins=False).\n"
        return CheckResult(
            "plugins",
            CheckStatus.FAIL,
            (
                f"{header}\n"
                f"{middle}"
                "Manual fix:\n"
                "  make install-plugins          # preferred — reads config, installs all missing\n"
                "  # or per-plugin:\n"
                "  claude plugin install <name>@<marketplace> --scope user\n"
                "\nIf `claude plugin install` reports a login error, run:\n"
                "  claude login"
            ),
        )

    # Tier-2 install (best effort). Capture per-plugin errors so the WARN
    # message can report WHY an install failed, not just that it's missing.
    tier2_install_errors: dict[str, str] = {}  # plugin_name → detail
    if config.auto_install_plugins:
        for _, name, marketplace in tier2_specs:
            if not plugin_exists(root, name):
                ok, detail = install_plugin(name, marketplace)
                if not ok:
                    tier2_install_errors[name] = detail

    missing_tier2 = [
        (lang, n) for lang, n, _ in tier2_specs if not plugin_exists(root, n)
    ]

    all_plugin_names = [n for n, _ in tier1_specs] + [n for _, n, _ in tier2_specs]
    skills = discover_plugin_skills(all_plugin_names, cache_root=root)
    if not skills:
        return CheckResult(
            "plugins",
            CheckStatus.FAIL,
            f"Plugin allowlist yielded 0 skills under {root}",
        )

    if missing_tier2:
        parts: list[str] = []
        for lang, name in missing_tier2:
            detail = tier2_install_errors.get(name)
            if detail:
                parts.append(f"{name} (for {lang}: {detail})")
            else:
                parts.append(f"{name} (for {lang})")
        return CheckResult(
            "plugins",
            CheckStatus.WARN,
            f"Language-conditional plugins missing: {', '.join(parts)}",
        )

    return CheckResult(
        "plugins",
        CheckStatus.PASS,
        f"{len(skills)} plugin skills discovered",
    )


def plugin_exists(cache_root: Path, plugin: str) -> bool:
    """Return True if ``plugin`` directory exists under any marketplace in ``cache_root``."""
    if not cache_root.is_dir():
        return False
    for marketplace_dir in cache_root.iterdir():
        if (marketplace_dir / plugin).is_dir():
            return True
    return False
