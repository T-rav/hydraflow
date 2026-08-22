"""The director's runtime boundary: S1–S6, and the assertion S4 makes load-bearing.

ADR-0137 records a **conditional** go, and this module is the condition. Its
probe (`scripts/director_capability_probe.py`) measured three things that
together make a flag-trusting design unsafe:

* isolation alone leaves **22** tools advertised, including ``Bash`` and ``Task``;
* ``--allowedTools`` narrows nothing — it is a permission filter, not a surface
  filter;
* denying **every name the init frame advertised** still leaves **2** enabled,
  so the advertised array is incomplete and a name deny-list is *fail-open* the
  moment the CLI ships a new tool.

The conclusion the ADR draws is the one this module implements: the deny-list
(S3) is a starting posture and never the proof; the proof is
:func:`assert_observed_surface`, which reads the boundary the runtime was
actually handed off the turn's own ``system/init`` frame and refuses when it
cannot see an empty one. "Absent" is never read as "empty" — that is precisely
the CLI-upgrade shape the assertion exists to catch, and reading a missing key
as a pass would reproduce the fail-open error inside the fix for it.

Two framing rules from the same evidence, in :func:`turn_failed` and
:func:`last_init_frame`:

* ``result.subtype`` read ``"success"`` on a frame whose ``is_error`` was
  ``true``. **``is_error`` is authoritative and ``subtype`` must never gate
  success** (S5).
* a single turn can emit many ``system/init`` frames under upstream retry, so
  the last one describes the session that actually proceeded.

Everything here is pure or filesystem-only — no CLI is spawned from this module.
The spawn lives in :mod:`director_turn_runner`, which is where the air-gap seam
is declared.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("director_sandbox")


class DirectorSandboxError(RuntimeError):
    """The runtime boundary could not be constructed or proven.

    Raised rather than degraded, per ADR-0137 S1: *"Sandbox construction fails
    closed; falling back to the ``bypassPermissions`` command builder is
    forbidden."* A director that cannot prove its boundary must refuse to run.
    """


# --------------------------------------------------------------------------
# S1 — the environment allow-list. The whole scrub contract, in one place.
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

An allow-list, never a deny-list: a deny-list of known-secret names is fail-open
for the next variable someone invents. ``ANTHROPIC_BASE_URL`` /
``ANTHROPIC_AUTH_TOKEN`` carry the **virtual** gateway key only (S2); a real
upstream provider key must never occupy them, which is why the operator's own
value for ``ANTHROPIC_AUTH_TOKEN`` is dropped even though the name is allowed.
"""

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
"""S3's starting posture: every name the CLI advertises plus the two it does not.

``Glob`` and ``Grep`` are enabled without appearing in the advertised array —
discovered by the #11533 probe, and the reason this list can never be the proof.
:func:`assert_observed_surface` is the proof.
"""


def build_scrubbed_env(
    source_env: dict[str, str],
    *,
    home: str,
    config_dir: str,
    gateway_base_url: str | None = None,
    gateway_token: str | None = None,
) -> dict[str, str]:
    """Build the director's environment from the allow-list (S1/S2).

    Only :data:`DIRECTOR_ENV_ALLOWLIST` names survive from *source_env*, and
    ``HOME`` / ``CLAUDE_CONFIG_DIR`` are overwritten with the disposable sandbox
    paths. Any provider credential inherited from the operator's shell is
    dropped rather than forwarded: the sole credential the director may hold is
    the short-lived virtual key passed explicitly here.
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


# --------------------------------------------------------------------------
# S5 — framing discipline
# --------------------------------------------------------------------------


def parse_stream_json(raw: str) -> list[dict[str, Any]]:
    """Parse the CLI's ``stream-json`` output strictly — one JSON object per line.

    Raises on the first unparseable non-blank line. A director that tolerated
    junk framing would let a banner line or a partial write masquerade as a
    command, which is the malformed-command hazard #11537 requires to fail
    closed.
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


def turn_failed(frames: list[dict[str, Any]]) -> bool:
    """True when the turn failed, keyed on ``is_error`` — never on ``subtype``.

    The #11533 probe observed ``result.subtype == "success"`` alongside
    ``result.is_error is True`` for both an authentication failure and a
    connection refusal. Keying success on ``subtype`` is fail-open; ``is_error``
    is authoritative (ADR-0137 S5). A turn with no result frame at all counts as
    failed, so a killed or truncated turn cannot read as a success.
    """
    for frame in frames:
        if frame.get("type") == "result":
            return bool(frame.get("is_error"))
    return True


def last_init_frame(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the final ``system/init`` frame, tolerating repeats.

    A single turn emitted eleven init frames under upstream retry during the
    #11533 probe. A parser that assumes exactly one breaks; the last one
    describes the session that actually proceeded.
    """
    inits = [
        f for f in frames if f.get("type") == "system" and f.get("subtype") == "init"
    ]
    return inits[-1] if inits else None


def captured_session_id(frames: list[dict[str, Any]]) -> str | None:
    """Vendor session id from any frame that carries one.

    A **rotation hint** for the checkpoint, never ownership and never a resume
    handle: this runtime reconstructs from the capsule every turn.
    """
    for frame in frames:
        session_id = frame.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id
    return None


# --------------------------------------------------------------------------
# S4 — the observed-boundary assertion
# --------------------------------------------------------------------------


class SurfaceVerdict(StrEnum):
    """Why the observed boundary was or was not accepted."""

    VERIFIED = "verified"
    NO_INIT_FRAME = "no_init_frame"
    TOOLS_KEY_ABSENT = "tools_key_absent"
    TOOLS_NOT_EMPTY = "tools_not_empty"
    MCP_OR_PLUGINS_PRESENT = "mcp_or_plugins_present"
    RESIDUAL_CHANNEL_MOVED = "residual_channel_moved"
    CLI_VERSION_MISMATCH = "cli_version_mismatch"
    CLI_VERSION_UNOBSERVED = "cli_version_unobserved"


@dataclass(frozen=True)
class SurfaceObservation:
    """The outcome of S4's four-part assertion over one turn's init frame."""

    verdict: SurfaceVerdict
    detail: str = ""
    observed_tools: int = 0
    observed_agents: int = 0
    observed_skills: int = 0
    observed_slash_commands: int = 0

    @property
    def verified(self) -> bool:
        return self.verdict is SurfaceVerdict.VERIFIED


@dataclass(frozen=True)
class ProbeEvidence:
    """The committed probe evidence S4 asserts against.

    Loaded from ``tests/fixtures/director/director_capability_probe_evidence.json``
    — the sanitized artifact ADR-0137 D2's table is quoted from. It is the
    *baseline*, so a change in any of these numbers means the capability surface
    moved and the operator must re-probe before the director may dispatch again.
    """

    agent_cli_version: str
    residual_agents: int
    residual_skills: int
    residual_slash_commands: int

    @classmethod
    def from_json(cls, raw: str) -> ProbeEvidence:
        payload = json.loads(raw)
        version = payload.get("agent_cli_version")
        if not isinstance(version, str) or not version.strip():
            msg = (
                "probe evidence carries no agent_cli_version; S4's version fence "
                "cannot be armed against it"
            )
            raise DirectorSandboxError(msg)
        tools_proof = _proof_named(payload, "no_ambient_tools_or_credentials")
        observations = tools_proof.get("observations", {})
        return cls(
            agent_cli_version=version,
            residual_agents=_int_at(observations, "residual_agents_advertised"),
            residual_skills=_int_at(observations, "residual_skills_advertised"),
            residual_slash_commands=_int_at(
                observations, "residual_slash_commands_advertised"
            ),
        )

    @classmethod
    def load(cls, path: Path) -> ProbeEvidence:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            msg = (
                f"director probe evidence is unreadable at {path}: {exc}. The "
                "runtime boundary cannot be asserted without it, so the director "
                "refuses to run (ADR-0137 S4)."
            )
            raise DirectorSandboxError(msg) from exc
        return cls.from_json(raw)


def _proof_named(payload: dict[str, Any], name: str) -> dict[str, Any]:
    for proof in payload.get("proofs", []):
        if isinstance(proof, dict) and proof.get("proof") == name:
            return proof
    msg = f"probe evidence carries no {name!r} proof"
    raise DirectorSandboxError(msg)


def _int_at(observations: dict[str, Any], key: str) -> int:
    value = observations.get(key)
    if not isinstance(value, int):
        msg = f"probe evidence observation {key!r} is not an integer"
        raise DirectorSandboxError(msg)
    return value


_VERSION_TOKEN = re.compile(r"\d+(?:\.\d+)*")


def normalise_cli_version(value: str | None) -> str | None:
    """Reduce a CLI version string to its bare dotted token.

    The evidence records what ``claude --version`` printed
    (``"2.1.239 (Claude Code)"``) while an init frame carries a bare
    ``"2.1.239"``. Comparing the raw strings would make the fence fire on
    formatting rather than on a version change, which trains an operator to
    ignore it — the worst possible outcome for a gate.
    """
    if value is None:
        return None
    match = _VERSION_TOKEN.search(value)
    return match.group(0) if match else None


UNOBSERVED_CHANNEL = -1
"""Sentinel for a capability channel that is absent or not a collection.

Zero would be a lie in exactly F2's shape: a CLI that renames ``agents`` to
``subagents`` would read as "zero agents advertised" and verify. Parts 1 and 2
of S4 already refuse an absent key; part 3 must refuse one too, or the
assertion is fail-open on one of its own four legs.
"""


def _channel_len(init_frame: dict[str, Any], key: str) -> int:
    value = init_frame.get(key)
    return len(value) if isinstance(value, list | dict) else UNOBSERVED_CHANNEL


def _observed(
    verdict: SurfaceVerdict,
    counts: dict[str, int],
    *,
    detail: str = "",
    observed_tools: int = 0,
) -> SurfaceObservation:
    """Build an observation carrying the channel counts, spelled out.

    The counts travel as a dict because three helpers pass them through
    unchanged, and splatting a ``dict[str, int]`` into a dataclass with a
    ``str`` field is exactly the kind of thing a type checker is for.
    """
    return SurfaceObservation(
        verdict=verdict,
        detail=detail,
        observed_tools=observed_tools,
        observed_agents=counts["observed_agents"],
        observed_skills=counts["observed_skills"],
        observed_slash_commands=counts["observed_slash_commands"],
    )


def assert_observed_surface(
    init_frame: dict[str, Any] | None,
    *,
    evidence: ProbeEvidence,
    observed_cli_version: str | None = None,
) -> SurfaceObservation:
    """ADR-0137 S4, all four parts, fail-closed at every step.

    1. ``tools`` must be **present** and empty. Absent or renamed reads as
       *unverified*, never as "empty" — otherwise the assertion fails open on
       exactly the CLI-upgrade scenario it exists to catch.
    2. ``mcp_servers`` and ``plugins`` must be empty. The same present-or-
       unverified rule is applied for the same reason: a renamed key is a moved
       boundary, not an absent one.
    3. the ``agents`` / ``skills`` / ``slash_commands`` channels (finding F4)
       must be empty **or unchanged** from the committed counts. They are CLI
       built-ins that survive isolation by construction and are unreachable once
       ``Task`` and ``Skill`` are denied — but they are capability surface, and a
       change in them means the surface moved.
    4. the reported CLI version must match the evidence. A mismatch **re-arms
       the gate**: the evidence no longer describes this binary, so the operator
       must re-run the probe before the director may dispatch again.

    Returns an observation rather than raising, because the caller's response is
    a :class:`driver_contracts.RejectionReason` (``SANDBOX_UNVERIFIED``) and a
    discarded turn — a first-class refusal, not an exception path.
    """
    if init_frame is None:
        return SurfaceObservation(
            verdict=SurfaceVerdict.NO_INIT_FRAME,
            detail="the turn produced no system/init frame to assert against",
        )

    counts = {
        "observed_agents": _channel_len(init_frame, "agents"),
        "observed_skills": _channel_len(init_frame, "skills"),
        "observed_slash_commands": _channel_len(init_frame, "slash_commands"),
    }
    # The four parts are evaluated in order and the first failure wins, so the
    # reported verdict is deterministic and replayable from the same frame —
    # the same first-match-wins discipline ``admit_dispatch`` uses.
    for check in (_tools_are_observed_empty, _no_mcp_servers_or_plugins):
        failure = check(init_frame, counts)
        if failure is not None:
            return failure
    residual = _residual_channels_unmoved(counts, evidence)
    if residual is not None:
        return residual
    version = _cli_version_matches_evidence(
        init_frame, counts, evidence=evidence, observed_cli_version=observed_cli_version
    )
    if version is not None:
        return version
    return _observed(SurfaceVerdict.VERIFIED, counts)


def _tools_are_observed_empty(
    init_frame: dict[str, Any], counts: dict[str, int]
) -> SurfaceObservation | None:
    """S4 part 1 — present *and* empty. Absent never reads as empty."""
    if "tools" not in init_frame or not isinstance(init_frame["tools"], list):
        return _observed(
            SurfaceVerdict.TOOLS_KEY_ABSENT,
            counts,
            detail=(
                "the init frame carries no list-valued 'tools' key; an absent or "
                "renamed key reads as unverified, never as empty"
            ),
        )
    tools = init_frame["tools"]
    if tools:
        return _observed(
            SurfaceVerdict.TOOLS_NOT_EMPTY,
            counts,
            detail=f"{len(tools)} tools still enabled: {sorted(map(str, tools))[:8]}",
            observed_tools=len(tools),
        )
    return None


def _no_mcp_servers_or_plugins(
    init_frame: dict[str, Any], counts: dict[str, int]
) -> SurfaceObservation | None:
    """S4 part 2 — the same present-or-unverified rule, for the same reason."""
    for key in ("mcp_servers", "plugins"):
        value = init_frame.get(key)
        if not isinstance(value, list | dict) or value:
            return _observed(
                SurfaceVerdict.MCP_OR_PLUGINS_PRESENT,
                counts,
                detail=f"{key} is missing or non-empty on the init frame",
            )
    return None


def _residual_channels_unmoved(
    counts: dict[str, int], evidence: ProbeEvidence
) -> SurfaceObservation | None:
    """S4 part 3 — finding F4's uncovered channels: empty, or exactly as probed."""
    baseline = {
        "observed_agents": evidence.residual_agents,
        "observed_skills": evidence.residual_skills,
        "observed_slash_commands": evidence.residual_slash_commands,
    }
    for key, observed in counts.items():
        if observed == UNOBSERVED_CHANNEL:
            return _observed(
                SurfaceVerdict.RESIDUAL_CHANNEL_MOVED,
                counts,
                detail=(
                    f"{key} is absent from the init frame or is not a "
                    "collection; an unobservable channel reads as moved, never "
                    "as empty"
                ),
            )
        if observed not in (0, baseline[key]):
            return _observed(
                SurfaceVerdict.RESIDUAL_CHANNEL_MOVED,
                counts,
                detail=(
                    f"{key} observed {observed}, evidence records {baseline[key]}; "
                    "the capability surface moved and must be re-probed"
                ),
            )
    return None


def _cli_version_matches_evidence(
    init_frame: dict[str, Any],
    counts: dict[str, int],
    *,
    evidence: ProbeEvidence,
    observed_cli_version: str | None,
) -> SurfaceObservation | None:
    """S4 part 4 — the version fence that re-arms the gate on a CLI upgrade."""
    frame_version = init_frame.get("version")
    reported = normalise_cli_version(
        frame_version if isinstance(frame_version, str) else observed_cli_version
    )
    expected = normalise_cli_version(evidence.agent_cli_version)
    if reported is None:
        return _observed(
            SurfaceVerdict.CLI_VERSION_UNOBSERVED,
            counts,
            detail=(
                "no CLI version was observed on the init frame or at preflight; "
                "S4's version fence cannot be satisfied"
            ),
        )
    if reported != expected:
        return _observed(
            SurfaceVerdict.CLI_VERSION_MISMATCH,
            counts,
            detail=(
                f"CLI reports {reported}, evidence was recorded against "
                f"{expected}; re-run scripts/director_capability_probe.py"
            ),
        )
    return None


# --------------------------------------------------------------------------
# S1 — the disposable process boundary
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxPaths:
    """The three disposable directories one director turn is confined to."""

    root: Path
    home: Path
    cwd: Path
    config_dir: Path


@contextlib.contextmanager
def director_sandbox(*, base_dir: Path | None = None) -> Iterator[SandboxPaths]:
    """Create, yield and destroy one turn's disposable boundary (S1).

    An empty non-project working directory, a disposable ``HOME`` and a
    disposable ``CLAUDE_CONFIG_DIR``. The cwd is empty and outside the repo, so
    ``--setting-sources project`` loads nothing: there is no project
    ``.claude/settings.json`` and no ``CLAUDE.md`` to find. The probe proved
    this by planting hostile copies of both and observing no project memory
    path.

    Construction failure raises :class:`DirectorSandboxError` rather than
    yielding a partial boundary — S1 forbids degrading to the
    ``bypassPermissions`` builder, and a half-built sandbox is exactly that
    fallback wearing a different name.
    """
    try:
        root = Path(tempfile.mkdtemp(prefix="hf-director-", dir=base_dir))
    except OSError as exc:
        msg = f"could not create the director sandbox root: {exc}"
        raise DirectorSandboxError(msg) from exc
    paths = SandboxPaths(
        root=root, home=root / "home", cwd=root / "cwd", config_dir=root / "cfg"
    )
    try:
        for directory in (paths.home, paths.cwd, paths.config_dir):
            directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        shutil.rmtree(root, ignore_errors=True)
        msg = f"could not lay out the director sandbox under {root}: {exc}"
        raise DirectorSandboxError(msg) from exc
    try:
        yield paths
    finally:
        # The boundary is disposable by definition; a failure to remove it is
        # logged rather than raised, because it must not mask the turn's own
        # outcome.
        shutil.rmtree(root, ignore_errors=True)
