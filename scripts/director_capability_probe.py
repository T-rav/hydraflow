#!/usr/bin/env python3
"""Director capability probe — the eight boundary proofs behind ADR-0137 (#11533).

The Fable-director design in ``docs/proposals/fable-subagent-scheduling.md``
claims a contract-only sandbox: an isolated home and settings, a scrubbed
environment, no ambient tools or credentials, a disposable process tree, a
short-lived gateway key, strict JSON framing, and recovery that never depends
on vendor session history. This script tries to *falsify* each of those claims
and emits one sanitized evidence artifact.

Two lanes, deliberately separated so CI never needs credentials or a CLI:

* **hermetic** (default) — proofs that are pure Python plus a real local
  subprocess: environment scrubbing, process-tree teardown, short-lived key
  expiry. These run anywhere, including CI.
* **live** (``--live``) — proofs that require the actual ``claude`` CLI binary:
  JSON framing, session-id capture, resume loss, isolated settings/home, and
  the ambient tool/credential surface. Operator-run. The committed fixture in
  ``tests/fixtures/director/`` is the recorded output of a live run; CI
  validates that fixture's schema and never re-runs this lane.

The live lane is deliberately cheap: every live proof is observable from the
CLI's ``system/init`` frame or from a failure path, so no probe turn needs a
funded upstream. An unauthenticated CLI is sufficient — and is itself the
credential-boundary proof.

Usage::

    python3 scripts/director_capability_probe.py                 # hermetic only
    python3 scripts/director_capability_probe.py --live          # + live lane
    python3 scripts/director_capability_probe.py --live --out tests/fixtures/director/...

Sanitization is enforced by the schema, not by discipline: the evidence models
forbid unknown fields, and every value written is a bool, an int, an enum, or a
short shape descriptor. Prompts, model output, real session ids, key ids,
tokens and host paths never enter the artifact.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

DIRECTOR_PROBE_SCHEMA_VERSION = 1

TURN_TIMED_OUT = -1
"""Exit code the probe assigns when it killed a turn at its own budget."""

_SHA256_DIGEST_BYTES = 32
"""A retained key record must hold exactly a SHA-256 digest, never the token."""

# --------------------------------------------------------------------------
# The environment allow-list — the whole scrub contract, in one place.
# --------------------------------------------------------------------------

DIRECTOR_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "CLAUDE_CONFIG_DIR",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
    }
)
"""Every variable the director process is permitted to see.

``ANTHROPIC_BASE_URL`` / ``ANTHROPIC_AUTH_TOKEN`` carry the *virtual* gateway
key only. A real upstream provider key must never occupy them.
"""

_SECRET_NAME_PATTERN = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE|SESSION)", re.IGNORECASE
)

_SAFE_DESCRIPTOR = re.compile(r"^[a-z0-9][a-z0-9 ._:+-]{0,60}$")
"""String observations must match this lowercase descriptor grammar.

A whitelist, not a blacklist: anything carrying uppercase, ``/`` or ``=`` — most
base64 tokens and JWTs — is refused outright. The grammar alone is not enough
though, because plenty of secrets are lowercase (a raw UUID session id, a hex
digest, a ``ghp_`` token), so :data:`_SECRET_SHAPES` rejects those shapes too.
"""

_SECRET_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    re.compile(r"[0-9a-f]{16,}"),
    re.compile(r"^(?:gh[pousr]_|sk-|hf-|xox[baprs]-|eyj)"),
)
"""Lowercase shapes that pass the descriptor grammar but are still secrets.

In order: a raw UUID (exactly the vendor session id ``describe_id_shape``
exists to avoid recording), any long hex run (digests, key ids), and the common
token prefixes. Sanitization is claimed to be enforced by the schema rather than
by discipline, so it has to actually hold.
"""

# Tool names the CLI advertises today plus the two it does NOT advertise but
# still enables (Glob, Grep — discovered by the #11533 probe). The list is a
# *starting* deny-list; the load-bearing check is the observed-empty assertion
# in :func:`_probe_tool_surface`, never this list's completeness.
DIRECTOR_DENIED_TOOLS: tuple[str, ...] = (
    "Task",
    "Bash",
    "CronCreate",
    "CronDelete",
    "CronList",
    "DesignSync",
    "Edit",
    "EnterWorktree",
    "ExitWorktree",
    "NotebookEdit",
    "Read",
    "ReportFindings",
    "ScheduleWakeup",
    "SendMessage",
    "Skill",
    "TaskOutput",
    "TaskStop",
    "ToolSearch",
    "WebFetch",
    "WebSearch",
    "Workflow",
    "Write",
    "Glob",
    "Grep",
    "LS",
    "TodoWrite",
)


class ProofName(StrEnum):
    """The eight proofs issue #11533 requires."""

    JSON_FRAMING = "json_framing"
    SESSION_ID_CAPTURE = "session_id_capture"
    RESUME_LOSS = "resume_loss"
    ISOLATED_SETTINGS_HOME = "isolated_settings_home"
    ENVIRONMENT_SCRUBBING = "environment_scrubbing"
    PROCESS_TREE_TEARDOWN = "process_tree_teardown"
    SHORT_LIVED_KEY_EXPIRY = "short_lived_key_expiry"
    NO_AMBIENT_TOOLS_OR_CREDENTIALS = "no_ambient_tools_or_credentials"


class Verdict(StrEnum):
    """A proof either holds, is falsified, holds only under a constraint, or did not run."""

    PASS = "pass"
    PASS_WITH_CONSTRAINT = "pass_with_constraint"
    FAIL = "fail"
    NOT_RUN = "not_run"


class Lane(StrEnum):
    HERMETIC = "hermetic"
    LIVE = "live"


class ProofResult(BaseModel):
    """One boundary proof. ``observations`` holds scalars only — never content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proof: ProofName
    lane: Lane
    verdict: Verdict
    summary: str = Field(min_length=1, max_length=400)
    constraint: str | None = Field(default=None, max_length=600)
    observations: dict[str, bool | int | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _observations_carry_no_secrets(self) -> ProofResult:
        for key, value in self.observations.items():
            if not isinstance(value, str):
                continue
            if value.startswith(("/users/", "/home/", "/Users/", "/home")):
                raise ValueError(f"observation {key!r} leaks a host home path")
            if not _SAFE_DESCRIPTOR.fullmatch(value):
                raise ValueError(
                    f"observation {key!r} holds {value[:16]!r}…, which is not a "
                    "lowercase shape descriptor; record a bool, an int, or a "
                    "descriptor instead of raw content"
                )
            if any(shape.search(value) for shape in _SECRET_SHAPES):
                raise ValueError(
                    f"observation {key!r} holds a secret-shaped value (uuid, hex "
                    "digest, or token prefix); record a shape descriptor instead"
                )
        if self.verdict is Verdict.PASS_WITH_CONSTRAINT and not self.constraint:
            raise ValueError(f"{self.proof} passed with a constraint but named none")
        return self


class ProbeEvidence(BaseModel):
    """The sanitized artifact. Unknown fields are refused, so nothing rides along."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = DIRECTOR_PROBE_SCHEMA_VERSION
    evidence_kind: str = "director_capability_probe"
    recorded_at: str = Field(min_length=1, max_length=40)
    platform: str = Field(min_length=1, max_length=40)
    live_lane_ran: bool
    agent_cli_version: str | None = Field(default=None, max_length=40)
    proofs: tuple[ProofResult, ...]
    sanitization: dict[str, bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _every_proof_present_exactly_once(self) -> ProbeEvidence:
        seen = [p.proof for p in self.proofs]
        if len(set(seen)) != len(seen):
            raise ValueError("duplicate proof in evidence")
        missing = set(ProofName) - set(seen)
        if missing:
            raise ValueError(f"evidence omits required proofs: {sorted(missing)}")
        return self

    @property
    def overall_verdict(self) -> Verdict:
        """Worst verdict across the proofs.

        ``FAIL`` means a boundary claim was falsified — the only verdict that
        makes the run exit non-zero. ``NOT_RUN`` means the artifact is
        *incomplete* (the default hermetic run leaves the live lane unrun), which
        is expected locally but disqualifies the artifact as ADR evidence.
        """
        verdicts = {p.verdict for p in self.proofs}
        if Verdict.FAIL in verdicts:
            return Verdict.FAIL
        if Verdict.NOT_RUN in verdicts:
            return Verdict.NOT_RUN
        if Verdict.PASS_WITH_CONSTRAINT in verdicts:
            return Verdict.PASS_WITH_CONSTRAINT
        return Verdict.PASS


# --------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# --------------------------------------------------------------------------


def build_scrubbed_env(
    source_env: dict[str, str],
    *,
    home: str,
    config_dir: str,
    gateway_base_url: str | None = None,
    gateway_token: str | None = None,
) -> dict[str, str]:
    """Build the director's environment from an allow-list, never a deny-list.

    Only :data:`DIRECTOR_ENV_ALLOWLIST` names survive from *source_env*, and
    ``HOME`` / ``CLAUDE_CONFIG_DIR`` are overwritten with the disposable
    sandbox paths. Any provider credential inherited from the operator's shell
    is dropped rather than forwarded: the sole credential the director may hold
    is the short-lived virtual key passed explicitly here.
    """
    scrubbed = {
        key: value
        for key, value in source_env.items()
        if key in DIRECTOR_ENV_ALLOWLIST and key not in {"ANTHROPIC_AUTH_TOKEN"}
    }
    scrubbed["HOME"] = home
    scrubbed["CLAUDE_CONFIG_DIR"] = config_dir
    scrubbed.setdefault("PATH", os.defpath)
    if gateway_base_url is not None:
        scrubbed["ANTHROPIC_BASE_URL"] = gateway_base_url
    else:
        scrubbed.pop("ANTHROPIC_BASE_URL", None)
    if gateway_token is not None:
        scrubbed["ANTHROPIC_AUTH_TOKEN"] = gateway_token
    return scrubbed


def leaked_secret_names(env: dict[str, str]) -> list[str]:
    """Names in *env* that look like credentials but are not the virtual key."""
    return sorted(
        name
        for name in env
        if _SECRET_NAME_PATTERN.search(name) and name != "ANTHROPIC_AUTH_TOKEN"
    )


def parse_stream_json(raw: str) -> list[dict[str, Any]]:
    """Parse the CLI's ``stream-json`` output strictly — one JSON object per line.

    Raises on the first unparseable non-blank line. A director that tolerates
    junk framing would let a banner line or a partial write masquerade as a
    command.
    """
    frames: list[dict[str, Any]] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            frame = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"unframed output at line {number}: {exc}") from exc
        if not isinstance(frame, dict):
            raise ValueError(f"line {number} is not a JSON object")
        frames.append(frame)
    return frames


def _frames_or_empty(raw: str) -> list[dict[str, Any]]:
    """Parse frames, degrading to empty rather than aborting the whole probe.

    The framing proof itself uses :func:`parse_stream_json` directly so that
    unframed output is recorded as a failure; every other proof only needs the
    frames it can get, and must not lose its own verdict to a banner line.
    """
    if not raw.strip():
        return []
    try:
        return parse_stream_json(raw)
    except ValueError:
        return []


def turn_failed(frames: list[dict[str, Any]]) -> bool:
    """True when the turn failed, keyed on ``is_error`` — never on ``subtype``.

    The #11533 probe observed ``result.subtype == "success"`` alongside
    ``result.is_error is True`` for both an authentication failure and a
    connection refusal. Keying success on ``subtype`` is fail-open; ``is_error``
    is the authoritative field.
    """
    for frame in frames:
        if frame.get("type") == "result":
            return bool(frame.get("is_error"))
    return True


def last_init_frame(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the final ``system/init`` frame, tolerating repeats.

    A single turn emitted eleven init frames under upstream retry during the
    #11533 probe. A parser that assumes exactly one init frame breaks; the last
    one describes the session that actually proceeded.
    """
    inits = [
        f for f in frames if f.get("type") == "system" and f.get("subtype") == "init"
    ]
    return inits[-1] if inits else None


def captured_session_id(frames: list[dict[str, Any]]) -> str | None:
    """Vendor session id from any frame that carries one."""
    for frame in frames:
        session_id = frame.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id
    return None


def describe_id_shape(value: str | None) -> str:
    """Describe an identifier without reproducing it (sanitization)."""
    if value is None:
        return "absent"
    if re.fullmatch(r"[0-9a-fA-F-]{36}", value):
        return "uuid-v4-shape"
    return f"opaque-len-{len(value)}"


# --------------------------------------------------------------------------
# Hermetic proofs
# --------------------------------------------------------------------------


def _probe_environment_scrubbing() -> ProofResult:
    hostile = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/should/be/replaced",
        "ANTHROPIC_API_KEY": "sk-live-REDACTED",
        "AWS_SECRET_ACCESS_KEY": "REDACTED",
        "GH_TOKEN": "ghp-REDACTED",
        "HYDRAFLOW_GATEWAY_TOKEN": "REDACTED",
        "SSH_AUTH_SOCK": "/private/tmp/agent.sock",
        "LANG": "en_US.UTF-8",
    }
    scrubbed = build_scrubbed_env(
        hostile,
        home="/sandbox/home",
        config_dir="/sandbox/cfg",
        gateway_base_url="http://127.0.0.1:1/gw",
        gateway_token="hf-virtual-REDACTED",
    )
    leaked = leaked_secret_names(scrubbed)
    offered_secrets = leaked_secret_names(hostile)
    unexpected = sorted(set(scrubbed) - DIRECTOR_ENV_ALLOWLIST)
    # `offered_secrets` guards against a vacuous pass: zero leaks out of zero
    # secrets offered would prove nothing.
    ok = (
        bool(offered_secrets)
        and not leaked
        and not unexpected
        and scrubbed["HOME"] == "/sandbox/home"
    )
    return ProofResult(
        proof=ProofName.ENVIRONMENT_SCRUBBING,
        lane=Lane.HERMETIC,
        verdict=Verdict.PASS if ok else Verdict.FAIL,
        summary=(
            "Child env is built from an allow-list; provider keys, gh tokens, the "
            "gateway control token and the ssh agent socket are all dropped."
        ),
        observations={
            "hostile_vars_offered": len(hostile),
            "secret_shaped_vars_offered": len(offered_secrets),
            "vars_surviving": len(scrubbed),
            "secret_shaped_leaks": len(leaked),
            "vars_outside_allowlist": len(unexpected),
            "home_overwritten": scrubbed["HOME"] == "/sandbox/home",
            "only_credential_is_virtual_key": scrubbed.get("ANTHROPIC_AUTH_TOKEN")
            is not None
            and not leaked,
        },
    )


def _pid_alive(pid: int) -> bool:
    """True when *pid* still exists (signal 0 probes without delivering)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _probe_process_tree_teardown() -> ProofResult:
    """Spawn a real process group with a grandchild, then reap the whole tree."""
    marker = Path(tempfile.mkdtemp(prefix="fablep0-teardown-")) / "pids.txt"
    try:
        return _teardown_proof(marker)
    finally:
        shutil.rmtree(marker.parent, ignore_errors=True)


def _teardown_proof(marker: Path) -> ProofResult:
    """Spawn the tree, reap it, and report survivors."""
    from process_group import kill_process_group  # noqa: PLC0415 — script-local import

    # Parent forks a grandchild; both write their pid and sleep well past the probe.
    script = (
        "import os, sys, time, subprocess\n"
        f"p = open({str(marker)!r}, 'w')\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(120)'])\n"
        "p.write(f'{os.getpid()}\\n{child.pid}\\n')\n"
        "p.flush(); p.close()\n"
        "time.sleep(120)\n"
    )
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", script],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    pids: list[int] = []
    if marker.exists():
        pids = [int(x) for x in marker.read_text().split() if x.strip()]

    kill_process_group(proc)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=15)

    # Poll for the group to drain rather than sleeping a fixed interval, which
    # is a flake window on a loaded runner.
    survivors = list(pids)
    deadline = time.monotonic() + 10.0
    while survivors and time.monotonic() < deadline:
        survivors = [pid for pid in survivors if _pid_alive(pid)]
        if survivors:
            time.sleep(0.05)

    for pid in survivors:  # never leave a probe process behind
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)

    ok = bool(pids) and not survivors
    return ProofResult(
        proof=ProofName.PROCESS_TREE_TEARDOWN,
        lane=Lane.HERMETIC,
        verdict=Verdict.PASS if ok else Verdict.FAIL,
        summary=(
            "kill_process_group reaps a real two-level process tree; no descendant "
            "of a cancelled director turn survives."
        ),
        observations={
            "descendants_spawned": len(pids),
            "descendants_surviving_after_teardown": len(survivors),
            "start_new_session_used": True,
        },
    )


def _probe_short_lived_key_expiry() -> ProofResult:
    from hydraflow_gateway.keys import (  # noqa: PLC0415 — script-local import
        ExpiredVirtualKey,
        VirtualKeyStore,
    )
    from hydraflow_gateway.models import (  # noqa: PLC0415 — script-local import
        MintKeyRequest,
        PrincipalKind,
        ProviderBinding,
        RepoClass,
    )

    clock = {"t": 1000.0}
    store = VirtualKeyStore(
        max_ttl_seconds=300,
        wall_clock=lambda: 1_700_000_000.0,
        monotonic=lambda: clock["t"],
    )
    minted = store.mint(
        MintKeyRequest(
            principal_kind=PrincipalKind.SPAWN,
            principal_id="director",
            spawn_id="probe-director-1",
            repo_slug="T-rav/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ANTHROPIC,
            ttl_seconds=60,
        )
    )
    resolved_before = store.resolve(minted.token) is not None

    # Sample the retained record BEFORE advancing the clock: resolve() deletes
    # an expired record, so inspecting afterwards would always find nothing and
    # the retention claim would be vacuously true.
    record = next(iter(getattr(store, "_records", {}).values()), None)
    retained = getattr(record, "token_digest", None)
    digest_only = (
        record is not None
        and isinstance(retained, bytes)
        and len(retained) == _SHA256_DIGEST_BYTES
        and retained != minted.token.encode()
        and minted.token not in repr(record)
    )

    clock["t"] += 61.0
    expired = False
    try:
        store.resolve(minted.token)
    except ExpiredVirtualKey:
        expired = True

    ok = resolved_before and expired and digest_only
    return ProofResult(
        proof=ProofName.SHORT_LIVED_KEY_EXPIRY,
        lane=Lane.HERMETIC,
        verdict=Verdict.PASS if ok else Verdict.FAIL,
        summary=(
            "A 60s virtual key resolves before its TTL and is refused after it; "
            "the store retains only a SHA-256 digest, never the token."
        ),
        observations={
            "record_sampled_before_expiry": record is not None,
            "resolved_before_ttl": resolved_before,
            "refused_after_ttl": expired,
            "plaintext_token_retained": not digest_only,
            "ttl_seconds": 60,
            "active_records_after_expiry": store.active_count,
        },
    )


# --------------------------------------------------------------------------
# Live proofs (operator lane)
# --------------------------------------------------------------------------


def _sandbox_dirs() -> tuple[Path, Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="fablep0-sandbox-"))
    home, cwd, cfg = root / "home", root / "cwd", root / "cfg"
    for path in (home, cwd, cfg):
        path.mkdir(parents=True)
    return home, cwd, cfg


def _run_director_turn(
    *,
    cli: str,
    extra_args: list[str],
    plant_hostile_project_files: bool = False,
    gateway_base_url: str | None = None,
    gateway_token: str | None = None,
    timeout_seconds: int = 180,
) -> tuple[int, str, str]:
    """Spawn one isolated ``claude -p`` turn and return (rc, stdout, stderr).

    The disposable sandbox is created and torn down here, so a timeout or a
    missing binary cannot leak a temp tree onto the operator's machine.
    """
    home, cwd, cfg = _sandbox_dirs()
    try:
        return _spawn_turn(
            cli=cli,
            extra_args=extra_args,
            plant_hostile_project_files=plant_hostile_project_files,
            home=home,
            cwd=cwd,
            cfg=cfg,
            gateway_base_url=gateway_base_url,
            gateway_token=gateway_token,
            timeout_seconds=timeout_seconds,
        )
    finally:
        shutil.rmtree(cwd.parent, ignore_errors=True)


def _spawn_turn(
    *,
    cli: str,
    extra_args: list[str],
    plant_hostile_project_files: bool,
    home: Path,
    cwd: Path,
    cfg: Path,
    gateway_base_url: str | None = None,
    gateway_token: str | None = None,
    timeout_seconds: int = 180,
) -> tuple[int, str, str]:
    """Run the turn inside an already-created sandbox."""
    if plant_hostile_project_files:
        (cwd / ".claude").mkdir()
        (cwd / ".claude" / "settings.json").write_text(
            json.dumps({"env": {"HOSTILE_PROJECT_VAR": "1"}})
        )
        (cwd / "CLAUDE.md").write_text("HOSTILE PROJECT MEMORY — must not be loaded\n")

    env = build_scrubbed_env(
        dict(os.environ),
        home=str(home),
        config_dir=str(cfg),
        gateway_base_url=gateway_base_url,
        gateway_token=gateway_token,
    )
    cmd = [
        cli,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--setting-sources",
        "project",
        "--max-turns",
        "1",
        *extra_args,
    ]
    from process_group import kill_process_group  # noqa: PLC0415 — script-local import

    # Popen + kill_process_group rather than subprocess.run(timeout=...): on a
    # timeout subprocess.run kills only the direct child, leaving the CLI's
    # descendants alive — the exact leak S6 forbids, and the timeout path is
    # reached in practice by the credential turn.
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate("probe\n", timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        kill_process_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover — defensive
            stdout, stderr = "", ""
        # rc -1 marks "killed at the probe's budget", which is a materially
        # weaker observation than a clean non-zero exit and is reported as such.
        return TURN_TIMED_OUT, stdout or "", stderr or ""
    return proc.returncode, stdout, stderr


def _probe_framing_and_session(cli: str) -> tuple[ProofResult, ProofResult]:
    rc, stdout, _stderr = _run_director_turn(
        cli=cli, extra_args=["--disallowedTools", ",".join(DIRECTOR_DENIED_TOOLS)]
    )
    try:
        frames = parse_stream_json(stdout)
        framing_ok = True
        framing_error = ""
    except ValueError as exc:
        frames, framing_ok = [], False
        framing_error = re.sub(r"[^a-z0-9 ._:+-]", "", str(exc).lower())[:60]

    inits = [
        f for f in frames if f.get("type") == "system" and f.get("subtype") == "init"
    ]
    has_result = any(f.get("type") == "result" for f in frames)
    subtype_says_success = any(
        f.get("type") == "result" and f.get("subtype") == "success" for f in frames
    )
    is_error = turn_failed(frames)

    framing = ProofResult(
        proof=ProofName.JSON_FRAMING,
        lane=Lane.LIVE,
        verdict=Verdict.PASS_WITH_CONSTRAINT if framing_ok else Verdict.FAIL,
        summary=(
            "Every stream-json line parses as a JSON object; frame types are "
            "system/init, assistant and result."
        ),
        constraint=(
            "Two framing hazards are real and the parser MUST handle both: a single "
            "turn can emit MANY system/init frames under upstream retry (last-init-wins), "
            "and result.subtype can read 'success' while result.is_error is true. "
            "is_error is authoritative; subtype must never gate success."
        ),
        observations={
            "frames_parsed": len(frames),
            "unparseable_lines": 0 if framing_ok else 1,
            "parse_error_shape": framing_error or "none",
            "init_frames_observed": len(inits),
            "result_frame_present": has_result,
            "subtype_reported_success": subtype_says_success,
            "is_error_reported": is_error,
            "subtype_disagrees_with_is_error": subtype_says_success and is_error,
            "cli_exit_code": rc,
        },
    )

    session_id = captured_session_id(frames)
    session = ProofResult(
        proof=ProofName.SESSION_ID_CAPTURE,
        lane=Lane.LIVE,
        verdict=Verdict.PASS if session_id else Verdict.FAIL,
        summary=(
            "The vendor session id is captured from the turn's frames and is "
            "recorded as a rotation hint only, never as ownership."
        ),
        observations={
            "session_id_captured": session_id is not None,
            "session_id_shape": describe_id_shape(session_id),
            "captured_even_on_failed_turn": session_id is not None and is_error,
            "is_hydraflow_factory_session_id": False,
        },
    )
    return framing, session


def _probe_resume_loss(cli: str) -> ProofResult:
    dead_session = "00000000-0000-4000-8000-000000000000"
    rc, stdout, stderr = _run_director_turn(
        cli=cli,
        extra_args=[
            "--resume",
            dead_session,
            "--disallowedTools",
            ",".join(DIRECTOR_DENIED_TOOLS),
        ],
    )
    frames = _frames_or_empty(stdout)
    # Work "proceeded" only if the model actually produced a turn. A lone
    # terminal result frame reporting the failure is the fail-closed signal,
    # not evidence that a fresh session silently took over.
    proceeded = any(f.get("type") in {"assistant", "user"} for f in frames)
    detected = (rc != 0 or turn_failed(frames)) and not proceeded
    result_subtype = next(
        (
            str(f.get("subtype") or "absent")
            for f in frames
            if f.get("type") == "result"
        ),
        "absent",
    )
    return ProofResult(
        proof=ProofName.RESUME_LOSS,
        lane=Lane.LIVE,
        verdict=Verdict.PASS if detected else Verdict.FAIL,
        summary=(
            "Resuming a dead vendor session fails closed: non-zero exit, a diagnostic "
            "on stderr, and a terminal result frame with is_error true. No assistant "
            "turn is produced, so a lost session can never be mistaken for a fresh "
            "one — the driver reconstructs from the capsule rather than proceeding blind."
        ),
        observations={
            "cli_exit_code": rc,
            "frames_on_stdout": len(frames),
            "diagnostic_on_stderr": bool(stderr.strip()),
            "result_frame_subtype": result_subtype,
            "result_frame_is_error": turn_failed(frames),
            "assistant_turn_produced": proceeded,
            "silently_started_fresh_session": proceeded,
            "resume_loss_is_detectable": detected,
        },
    )


def _init_of(
    cli: str, extra_args: list[str], **kw: object
) -> tuple[dict[str, Any], int, bool]:
    """Run one turn and return (last init frame, exit code, init-frame-seen).

    The third element matters: a turn that produced no init frame yields an
    empty dict, and several derived observations would read that as a *positive*
    result ("the allow-list narrowed the surface to zero"). Callers must gate on
    it so a failed turn can never masquerade as a finding.
    """
    rc, out, _err = _run_director_turn(cli=cli, extra_args=extra_args, **kw)  # type: ignore[arg-type]
    init = last_init_frame(_frames_or_empty(out))
    return init or {}, rc, init is not None


def _probe_isolation_and_tool_surface(cli: str) -> tuple[ProofResult, ProofResult]:
    # Five turns, because every claim the ADR makes must be MEASURED here rather
    # than asserted from an operator's exploratory session.
    baseline_init, baseline_rc, baseline_seen = _init_of(
        cli, [], plant_hostile_project_files=True
    )
    baseline_tools = list(baseline_init.get("tools") or [])

    # (2) allow-list: does naming one tool narrow the surface at all?
    allowlist_init, _, allowlist_seen = _init_of(cli, ["--allowedTools", "Read"])
    allowlist_tools = list(allowlist_init.get("tools") or [])

    # (3) deny exactly what the CLI advertised: is the advertised array complete?
    deny_advertised = [t for t in baseline_tools if isinstance(t, str)]
    advertised_init, _, advertised_seen = _init_of(
        cli,
        ["--disallowedTools", ",".join(deny_advertised)] if deny_advertised else [],
    )
    after_denying_advertised = list(advertised_init.get("tools") or [])

    # (4) exhaustive deny-list: can the surface actually reach empty?
    denied_init, denied_rc, denied_seen = _init_of(
        cli,
        ["--disallowedTools", ",".join(DIRECTOR_DENIED_TOOLS)],
        plant_hostile_project_files=True,
    )

    # (5) the RUNTIME configuration: the virtual gateway key is present and
    # points at a dead local endpoint. If the CLI silently fell back to the
    # operator's keychain this turn would authenticate; it must not.
    cred_rc, cred_out, cred_err = _run_director_turn(
        cli=cli,
        extra_args=["--disallowedTools", ",".join(DIRECTOR_DENIED_TOOLS)],
        gateway_base_url="http://127.0.0.1:9/gateway-probe",
        gateway_token="hf-virtual-probe-not-a-real-key",
        timeout_seconds=90,
    )
    cred_frames = _frames_or_empty(cred_out)
    cred_init = last_init_frame(cred_frames) or {}
    cred_init_frames = [
        f
        for f in cred_frames
        if f.get("type") == "system" and f.get("subtype") == "init"
    ]
    cred_text = (json.dumps(cred_frames) + cred_out + cred_err).lower()
    cred_timed_out = cred_rc == TURN_TIMED_OUT
    # A turn is only *observed* to have completed if it produced a terminal
    # result frame. Without one, `turn_failed` is trivially true and would let a
    # timeout satisfy the credential claim by default — so authentication is
    # judged as "observed to have authenticated", and the absence of an
    # observation is reported separately rather than counted as a pass.
    cred_completed = any(f.get("type") == "result" for f in cred_frames)
    authenticated = cred_completed and not turn_failed(cred_frames)
    used_injected_endpoint = any(
        marker in cred_text
        for marker in ("connection refused", "econnrefused", "127.0.0.1")
    )

    memory_paths = json.dumps(baseline_init.get("memory_paths") or {})
    # The sandbox lays out <root>/home, <root>/cwd, <root>/cfg. A memory path
    # under /cfg/ is the isolated config dir (expected); a path under /cwd/ means
    # the hostile CLAUDE.md planted in the working directory WAS loaded.
    config_dir_scoped = "/cfg/" in memory_paths
    project_memory_loaded = "/cwd/" in memory_paths
    home_leaked = "/Users/" in memory_paths or "/home/" in memory_paths

    isolation = ProofResult(
        proof=ProofName.ISOLATED_SETTINGS_HOME,
        lane=Lane.LIVE,
        verdict=(
            Verdict.PASS
            if config_dir_scoped and not home_leaked and not project_memory_loaded
            else Verdict.FAIL
        ),
        summary=(
            "With an allow-list environment, a disposable HOME and CLAUDE_CONFIG_DIR "
            "and an empty working directory, the turn loads no MCP server and no "
            "plugin, and its only memory path is inside the disposable config dir. "
            "A hostile .claude/settings.json and CLAUDE.md planted in the working "
            "directory produce no project memory path."
        ),
        observations={
            "mcp_servers_loaded": len(baseline_init.get("mcp_servers") or []),
            "plugins_loaded": len(baseline_init.get("plugins") or []),
            "memory_path_confined_to_sandbox": config_dir_scoped,
            "operator_home_path_leaked": home_leaked,
            "hostile_project_files_planted": True,
            "hostile_project_memory_loaded": project_memory_loaded,
            "cli_exit_code": baseline_rc,
        },
    )

    denied_tools = list(denied_init.get("tools") or [])
    api_key_source = (
        re.sub(
            r"[^a-z0-9._-]",
            "",
            str(baseline_init.get("apiKeySource") or "absent").lower(),
        )[:40]
        or "absent"
    )
    # S4 is only satisfied if the key is PRESENT and empty. An absent or renamed
    # `tools` key must read as unverified, never as "empty".
    tools_key_present = "tools" in denied_init
    residual_channels = sum(
        len(denied_init.get(channel) or [])
        for channel in ("agents", "skills", "slash_commands", "mcp_servers", "plugins")
    )
    surface_empty = (
        denied_seen and tools_key_present and not denied_tools and not authenticated
    )

    credentials = ProofResult(
        proof=ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS,
        lane=Lane.LIVE,
        verdict=Verdict.PASS_WITH_CONSTRAINT if surface_empty else Verdict.FAIL,
        summary=(
            "No ambient credential reaches the isolated child: with no credential the "
            "turn fails authentication, and with only the virtual gateway key present "
            "it is never observed to authenticate against the host keychain. The tool "
            "surface reaches empty only under an explicit exhaustive deny-list, and "
            "only the deny-list turn's own init frame can attest to it."
        ),
        constraint=(
            "Isolation alone does NOT empty the tool surface, an allow-list does not "
            "narrow it, and the advertised tool array is incomplete — so a name "
            "deny-list is fail-open across CLI upgrades. The runtime MUST assert the "
            "init tools key is PRESENT and empty (absent/renamed reads as unverified), "
            "and must also account for the agents, skills and slash-command channels, "
            "which stay populated at zero tools. apiKeySource is not a trustworthy "
            "provenance signal and must not gate anything. The assertion is post-hoc: "
            "it inspects a turn that already ran, so the residual exposure is one turn."
        ),
        observations={
            "tools_with_isolation_only": len(baseline_tools),
            "baseline_init_frame_seen": baseline_seen,
            "allowlist_init_frame_seen": allowlist_seen,
            "tools_with_allowlist_of_one": len(allowlist_tools),
            "allowlist_narrows_surface": (
                allowlist_seen
                and baseline_seen
                and len(allowlist_tools) < len(baseline_tools)
            ),
            "advertised_denial_init_frame_seen": advertised_seen,
            "tools_after_denying_every_advertised_name": len(after_denying_advertised),
            "advertised_tool_array_is_complete": (
                advertised_seen and not after_denying_advertised
            ),
            "tools_with_exhaustive_denylist": len(denied_tools),
            "tools_key_present_on_init": tools_key_present,
            "credential_turn_completed": cred_completed,
            "credential_turn_killed_at_probe_budget": cred_timed_out,
            "credential_turn_authenticated": authenticated,
            "credential_turn_used_injected_endpoint": used_injected_endpoint,
            "ambient_credential_reached_child": authenticated,
            "credential_turn_init_frames": len(cred_init_frames),
            "credential_turn_api_key_source": (
                re.sub(
                    r"[^a-z0-9._-]",
                    "",
                    str(cred_init.get("apiKeySource") or "absent").lower(),
                )[:40]
                or "absent"
            ),
            "api_key_source_reported": api_key_source,
            "residual_agents_advertised": len(denied_init.get("agents") or []),
            "residual_skills_advertised": len(denied_init.get("skills") or []),
            "residual_slash_commands_advertised": len(
                denied_init.get("slash_commands") or []
            ),
            "residual_capability_entries_outside_tools": residual_channels,
            "cli_exit_code": denied_rc,
            "credential_turn_exit_code": cred_rc,
        },
    )
    return isolation, credentials


def _not_run(proof: ProofName) -> ProofResult:
    return ProofResult(
        proof=proof,
        lane=Lane.LIVE,
        verdict=Verdict.NOT_RUN,
        summary="Live lane not requested; run with --live and an installed agent CLI.",
    )


def _cli_version(cli: str) -> str | None:
    try:
        out = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [cli, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()[:40] or None


def run_probe(*, live: bool, cli: str) -> ProbeEvidence:
    """Run the hermetic lane, and the live lane when requested."""
    proofs: list[ProofResult] = [
        _probe_environment_scrubbing(),
        _probe_process_tree_teardown(),
        _probe_short_lived_key_expiry(),
    ]
    version: str | None = None
    if live:
        version = _cli_version(cli)
        framing, session = _probe_framing_and_session(cli)
        isolation, credentials = _probe_isolation_and_tool_surface(cli)
        proofs.extend(
            [framing, session, _probe_resume_loss(cli), isolation, credentials]
        )
    else:
        proofs.extend(
            _not_run(name)
            for name in (
                ProofName.JSON_FRAMING,
                ProofName.SESSION_ID_CAPTURE,
                ProofName.RESUME_LOSS,
                ProofName.ISOLATED_SETTINGS_HOME,
                ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS,
            )
        )

    order = list(ProofName)
    proofs.sort(key=lambda p: order.index(p.proof))
    return ProbeEvidence(
        recorded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        platform=sys.platform,
        live_lane_ran=live,
        agent_cli_version=version,
        proofs=tuple(proofs),
        sanitization={
            "raw_prompt_omitted": True,
            "raw_model_output_omitted": True,
            "vendor_session_ids_omitted": True,
            "virtual_key_ids_and_tokens_omitted": True,
            "host_paths_omitted": True,
            "raw_captures_deleted": True,
        },
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also run the live lane (requires the agent CLI; operator-run, not CI).",
    )
    parser.add_argument(
        "--cli", default="claude", help="Agent CLI binary (default: claude)."
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Write evidence JSON here."
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.live and shutil.which(args.cli) is None:
        print(f"--live requested but {args.cli!r} is not on PATH", file=sys.stderr)
        return 2

    evidence = run_probe(live=args.live, cli=args.cli)
    rendered = evidence.model_dump_json(indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered)
    else:
        sys.stdout.write(rendered)

    for proof in evidence.proofs:
        print(f"{proof.verdict.value:22} {proof.proof.value}", file=sys.stderr)
    print(f"\noverall: {evidence.overall_verdict.value}", file=sys.stderr)
    return 0 if evidence.overall_verdict is not Verdict.FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
