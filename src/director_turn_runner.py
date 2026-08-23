"""The one place a director process is spawned, and the only one (#11537).

Every constraint ADR-0137 D4 puts on the director's runtime is applied here and
nowhere else, so there is a single answer to "how is the director isolated?":

* **S1** — a disposable ``HOME``, ``CLAUDE_CONFIG_DIR`` and empty non-project
  working directory from :func:`director_sandbox.director_sandbox`, and an
  environment built by *replacing* the child's environment with the allow-list
  from :func:`director_sandbox.build_scrubbed_env`. Replacing is the point: the
  repo's ordinary ``run_subprocess_result`` helper *merges* extra variables on
  top of ``make_clean_env``, which keeps ``ANTHROPIC_API_KEY`` and the whole
  parent environment — right for a ``gh`` call, and the opposite of S1. So this
  runner goes one level lower, to ``SubprocessRunner.run_simple``, whose ``env``
  argument replaces rather than merges *and* which already carries the reap
  machinery below.
* **S2** — the only credential offered is a short-lived **parent-scoped virtual
  gateway key**, minted per turn through the same ``resolve_harness_env`` path
  every other spawn uses and revoked in a ``finally``. Nothing else survives the
  allow-list — in particular the operator's own ``ANTHROPIC_AUTH_TOKEN`` is
  dropped even though the *name* is allowed, because the name exists for the
  virtual key and not for a real one. Minting is fail-closed: if no key can be
  minted the director refuses at preflight rather than running credential-free
  turns that quietly fail authentication forever.
* **S3** — ``--disallowedTools`` carries
  :data:`director_sandbox.DIRECTOR_DENIED_TOOLS`, the starting posture. It is
  never the proof; :func:`director_sandbox.assert_observed_surface` is, and the
  caller applies it to the frame this runner returns.
* **S5** — output is parsed strictly, one JSON object per line, and failure is
  keyed on ``is_error``.
* **S6** — ``HostRunner.run_simple`` spawns with ``start_new_session=True``,
  registers the child with the runtime-wide reap registry, and calls
  ``kill_process_group`` from **both** its ``TimeoutError`` and its
  ``asyncio.CancelledError`` handlers, so a turn that exceeds its budget takes
  its whole descendant tree with it. Reusing it rather than hand-rolling the
  spawn is deliberate: the probe's own timeout path had exactly this defect
  (``subprocess.run(timeout=...)`` kills only the direct child) and #11632 had
  to fix it. A turn over budget is a *failed* turn, never one retried in place.

**No ``--resume``, ever.** The probe proved a dead session exits 1 with no
assistant turn, and #11537's acceptance criterion is that fresh reconstruction
succeeds without vendor session history. The vendor session id is captured off
the frames as a rotation hint for the checkpoint and is never fed back in — so
"can we reconstruct without it?" is not a question this runtime has to answer at
recovery time, because it never depends on the answer.

**Not a governed routing seam, and deliberately so** (ADR-0139, #11639). The
route-shadow ledger exists to compare the route a *dial* selected against the
route a policy would have selected, at the four seams where a worker's route is
actually chosen. The director has no such choice to record: S2 permits it
exactly one credential and exactly one route — the gateway — so it is pinned
rather than dialled, and `canonical_worker_role("fable-director")` correctly
returns ``None`` because a director is a parent, not a catalogued worker. When
#11541 lets a director's *children* run, each of those is a worker spawn and
goes through the governed seams like any other.

Air-gap: two independent seams, because one of them being aspirational is how
the s51/s56/s57 wedges happened. The ``SubprocessRunner`` is **injected** from
the ``build_services`` composition root, so the sandbox's ``FakeSubprocessRunner``
replaces the spawn outright; and ``_apply_sandbox_config_overrides`` additionally
pins ``execution_runtime=stage_subprocess``, under which nothing constructs this
runner at all. This module contains no lexical spawn primitive of its own, which
is why it holds no ``SANDBOX_SEAMS`` row — the scan would reject a declaration
for a module it never sees spawning.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from director_sandbox import (
    DIRECTOR_DENIED_TOOLS,
    DirectorSandboxError,
    build_scrubbed_env,
    captured_session_id,
    director_sandbox,
    last_init_frame,
    normalise_cli_version,
    parse_stream_json,
    turn_failed,
)
from execution import HostRunner

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

    from execution import SimpleResult, SubprocessRunner


logger = logging.getLogger("director_turn_runner")

PREFLIGHT_TIMEOUT_SECONDS = 30
"""Budget for the one ``--version`` call. Generous for a local binary."""


@dataclass(frozen=True)
class DirectorTurnResult:
    """One director turn, as observed. Nothing here is trusted; it is evidence."""

    frames: list[dict[str, Any]] = field(default_factory=list)
    exit_code: int | None = None
    timed_out: bool = False
    unframed_output: bool = False
    latency_ms: int = 0
    usd_cost: float = 0.0
    session_id: str | None = None
    stderr_excerpt: str = ""

    @property
    def init_frame(self) -> dict[str, Any] | None:
        """The last ``system/init`` frame — S5's last-init-wins rule."""
        return last_init_frame(self.frames)

    @property
    def failed(self) -> bool:
        """Keyed on ``is_error``; a timed-out or unframed turn is always failed."""
        if self.timed_out or self.unframed_output:
            return True
        return turn_failed(self.frames)

    @property
    def looks_like_resume_loss(self) -> bool:
        """The signature the probe recorded for a vendor-dropped session.

        A terminal error frame and **no assistant turn at all**. This runtime
        never asks for a resume, so this is not a resume we attempted — it is
        the vendor losing one on its own, which ADR-0137 requires to be
        detectable rather than silent. The recovery is free, because the next
        capsule is rebuilt from scratch regardless.
        """
        if self.timed_out or not self.frames:
            return False
        produced_assistant_turn = any(
            frame.get("type") == "assistant" for frame in self.frames
        )
        return turn_failed(self.frames) and not produced_assistant_turn


class DirectorTurnRunner:
    """Spawns one isolated, contract-only director turn per call.

    Constructed at the ``build_services`` composition root — never inside a
    method — so the instance is injectable and a MockWorld fake can be attached
    to it, which is the lesson #11602/#11615 cost this repo twice in one night.
    """

    def __init__(
        self,
        *,
        runner: SubprocessRunner | None = None,
        cli_path: str = "claude",
        timeout_seconds: int = 180,
        sandbox_base_dir: Path | None = None,
        mint_credential: Callable[[], Awaitable[dict[str, str]]] | None = None,
        revoke_credential: Callable[[dict[str, str]], Awaitable[None]] | None = None,
        bound_model: Callable[[dict[str, str]], str] | None = None,
        source_env: Mapping[str, str] | None = None,
    ) -> None:
        # Injected, never built inside a method: that is what lets the sandbox
        # substitute a FakeSubprocessRunner, and what #11602/#11615 cost this
        # repo twice in one night by getting backwards.
        self._runner = runner or HostRunner()
        self._cli_path = cli_path
        self._timeout_seconds = timeout_seconds
        self._sandbox_base_dir = sandbox_base_dir
        self._mint_credential = mint_credential
        self._revoke_credential = revoke_credential
        # #11541: when the mint was route-BOUND, the gateway will only serve a
        # body naming the model the binding names, so a bound turn has to say
        # which model it is running on. Injected rather than imported so this
        # module keeps knowing nothing about the gateway's client, and ``None``
        # (or an unbound lease, which returns "") leaves the argv exactly what
        # it was under shadow mode.
        self._bound_model = bound_model
        # The environment the allow-list filters. ADR-0137 S1 is explicit that
        # this is "an allow-list filter over the parent environment, not a
        # literal ``env -i``: PATH, LANG, LC_ALL and TMPDIR are inherited by
        # design". Passing an empty mapping here would satisfy the *scrub* while
        # breaking the *inheritance* — and the first casualty is PATH, so the
        # CLI is not even findable. Injectable so a test can prove what is
        # filtered rather than trusting the filter in isolation.
        self._source_env = source_env
        self._cli_version: str | None = None

    def _parent_env(self) -> dict[str, str]:
        return dict(self._source_env if self._source_env is not None else os.environ)

    @property
    def cli_version(self) -> str | None:
        """The CLI version observed at preflight, for S4's version fence."""
        return self._cli_version

    async def preflight(self) -> str:
        """Prove the boundary is constructible and learn the CLI's version.

        Fail-closed by design: the director must refuse to run rather than
        degrade, so an unavailable CLI, an unconstructible sandbox or an
        unreadable version all raise :class:`director_sandbox.DirectorSandboxError`
        here — at startup, where it stops the factory from believing a director
        is watching when none can.
        """
        with director_sandbox(base_dir=self._sandbox_base_dir) as paths:
            try:
                result = await self._runner.run_simple(
                    [self._cli_path, "--version"],
                    cwd=str(paths.cwd),
                    env=build_scrubbed_env(
                        self._parent_env(),
                        home=str(paths.home),
                        config_dir=str(paths.config_dir),
                    ),
                    timeout=PREFLIGHT_TIMEOUT_SECONDS,
                )
            except (OSError, TimeoutError) as exc:
                msg = (
                    f"the director CLI {self._cli_path!r} could not be launched: "
                    f"{exc}. The runtime boundary cannot be proven, so the "
                    "director refuses to run (ADR-0137 S1)."
                )
                raise DirectorSandboxError(msg) from exc
        version = normalise_cli_version(result.stdout)
        if version is None:
            msg = (
                f"the director CLI {self._cli_path!r} reported no parseable "
                "version; S4's version fence cannot be armed against the "
                "committed probe evidence"
            )
            raise DirectorSandboxError(msg)
        self._cli_version = version
        await self._prove_a_credential_can_be_minted()
        return version

    async def _prove_a_credential_can_be_minted(self) -> None:
        """S2, proven at boot rather than discovered one failed turn at a time.

        Without this the director runs, every turn fails authentication, and the
        shadow log fills with ``turn_error`` rows that look like a flaky model
        rather than an unconfigured gateway. Refusing here is the same
        fail-closed posture the rest of the boundary takes: a director that
        cannot obtain its one permitted credential must not run at all.
        """
        if self._mint_credential is None:
            msg = (
                "no gateway credential provider is wired for the director. "
                "ADR-0137 S2 permits exactly one credential — a short-lived "
                "parent-scoped virtual gateway key — and running without it "
                "would produce a shadow log of authentication failures rather "
                "than evidence. Configure the gateway lane "
                "(HYDRAFLOW_GATEWAY_CONTROL_TOKEN and a reachable "
                "gateway_base_url) or do not select execution_runtime="
                "fable_director."
            )
            raise DirectorSandboxError(msg)
        try:
            minted = await self._mint_credential()
        except Exception as exc:
            msg = f"the director's gateway credential could not be minted: {exc}"
            raise DirectorSandboxError(msg) from exc
        try:
            if not minted.get("ANTHROPIC_AUTH_TOKEN"):
                msg = (
                    "the gateway credential provider returned no "
                    "ANTHROPIC_AUTH_TOKEN; the director has no credential and "
                    "refuses to run (ADR-0137 S2)"
                )
                raise DirectorSandboxError(msg)
        finally:
            await self._release(minted)

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        """Run one contract-only turn and return what was observed.

        Returns rather than raises for every *turn* failure — a timeout, an
        error frame, unframed output. Those are outcomes the caller records and
        fails closed on. Only a failure to construct the boundary itself raises,
        because that is a refusal to run rather than a run that went badly.
        """
        started = time.monotonic()
        credential = await self._mint()
        try:
            with director_sandbox(base_dir=self._sandbox_base_dir) as paths:
                env = build_scrubbed_env(
                    self._parent_env(),
                    home=str(paths.home),
                    config_dir=str(paths.config_dir),
                    gateway_base_url=credential.get("ANTHROPIC_BASE_URL"),
                    gateway_token=credential.get("ANTHROPIC_AUTH_TOKEN"),
                )
                try:
                    result = await self._runner.run_simple(
                        self._argv(self._bound_model_of(credential)),
                        cwd=str(paths.cwd),
                        env=env,
                        timeout=self._timeout_seconds,
                        input=prompt.encode("utf-8"),
                    )
                except TimeoutError:
                    # The runner has already reaped the whole process group (S6).
                    logger.warning(
                        "director turn exceeded its %ds budget; process group reaped",
                        self._timeout_seconds,
                    )
                    return DirectorTurnResult(
                        timed_out=True, latency_ms=_elapsed_ms(started)
                    )
                except OSError as exc:
                    msg = f"could not spawn the director turn: {exc}"
                    raise DirectorSandboxError(msg) from exc
        finally:
            # The key outlives the turn only until its TTL otherwise, and a
            # director turn is short — revoking narrows the window that a leaked
            # sandbox path or a stray core file could be replayed from.
            await self._release(credential)
        return self._observed(result, started)

    # -- internals ----------------------------------------------------------

    def _bound_model_of(self, credential: dict[str, str]) -> str:
        """The model this turn's lease binds it to, or ``""`` when unbound."""
        if self._bound_model is None or not credential:
            return ""
        return self._bound_model(credential)

    def _argv(self, bound_model: str = "") -> list[str]:
        """The spawn's argv. ``--resume`` is absent and must stay absent.

        ``--model`` appears **only** when the turn's credential is route-bound.
        An unbound turn is spawned with the argv it always had, so the shadow
        path stays byte-identical; a bound one must name the binding's model or
        the gateway refuses its first request as ``model-not-bound`` (#11541).
        """
        argv = [
            self._cli_path,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            # An explicit source with an empty non-project cwd loads nothing —
            # S1 requires the flag to be passed rather than left to the default.
            "--setting-sources",
            "project",
            "--max-turns",
            "1",
            "--disallowedTools",
            ",".join(DIRECTOR_DENIED_TOOLS),
        ]
        if bound_model:
            argv += ["--model", bound_model]
        return argv

    async def _mint(self) -> dict[str, str]:
        """Mint this turn's short-lived virtual gateway key (S2).

        Returns an empty mapping when no provider is wired. That path is
        unreachable in production — :meth:`preflight` refuses to start a
        director without one — and exists so a unit test can exercise the turn
        machinery without standing up a gateway.
        """
        if self._mint_credential is None:
            return {}
        return await self._mint_credential()

    async def _release(self, credential: dict[str, str]) -> None:
        """Best-effort revoke. Never raises into the turn's own outcome."""
        if self._revoke_credential is None or not credential:
            return
        try:
            await self._revoke_credential(credential)
        except Exception:
            logger.warning(
                "director turn: gateway key revocation failed; the key's TTL "
                "remains the fallback",
                exc_info=True,
            )

    def _observed(self, result: SimpleResult, started: float) -> DirectorTurnResult:
        try:
            frames = parse_stream_json(result.stdout)
        except ValueError as exc:
            logger.warning("director turn emitted unframed output: %s", exc)
            return DirectorTurnResult(
                exit_code=result.returncode,
                unframed_output=True,
                latency_ms=_elapsed_ms(started),
                stderr_excerpt=result.stderr[-500:],
            )
        return DirectorTurnResult(
            frames=frames,
            exit_code=result.returncode,
            latency_ms=_elapsed_ms(started),
            usd_cost=_turn_cost(frames),
            session_id=captured_session_id(frames),
            stderr_excerpt=result.stderr[-500:],
        )


def _elapsed_ms(started: float) -> int:
    return max(int((time.monotonic() - started) * 1000), 0)


def _turn_cost(frames: list[dict[str, Any]]) -> float:
    """The turn's USD spend, off its own result frame. Zero when unreported."""
    for frame in frames:
        if frame.get("type") != "result":
            continue
        cost = frame.get("total_cost_usd")
        if isinstance(cost, int | float) and cost >= 0:
            return float(cost)
    return 0.0


CAPSULE_OPEN = "<capsule>"
CAPSULE_CLOSE = "</capsule>"
"""Delimiters for the capsule payload. Load-bearing: a turn is reconstructable
from what sits between them and nothing else, and tests slice on them."""


def render_capsule_prompt(capsule_json: str) -> str:
    """The turn's entire input: the capsule, and the shape of the reply.

    Everything the director is allowed to know arrives in the capsule, and
    everything it is allowed to do arrives as the command schema. No ambient
    repository access, no conversation history, no prior turn — the whole point
    of a capsule is that a turn is reconstructable from it alone.

    The capsule goes **last** and inside a tag, because it is the long,
    variable part: a model reads instructions placed before a large payload more
    reliably than instructions buried after one, and the delimiters make the
    boundary between instruction and data unambiguous rather than positional.
    """
    return f"""Decide what should happen next for one HydraFlow issue, and reply with
exactly one DirectorCommand.

You are a HydraFlow issue director. Everything you are allowed to know about the
issue is in the capsule block at the end of this message; there is nothing else
to consult and no earlier turn to remember.

Think the decision through before answering: read the goal, the live stage label
and the budget, work out whether an extra worker would actually shorten this
phase, and only then choose one of the three replies below. Keep that reasoning
to yourself — the reply is the JSON object and nothing else.

Reply with EXACTLY ONE line of JSON and nothing else — no prose, no code fence,
no explanation outside the object. It must be one of these three shapes:

  {{"kind": "dispatch_workers", "dispatches": [...], "rationale": "..."}}
  {{"kind": "yield", "rationale": "..."}}
  {{"kind": "finish", "rationale": "..."}}

Any other shape, or any extra field, and the turn is discarded.

Rules for a dispatch:

- Request only roles listed in the capsule's `allowed_roles`.
- Name a model **tier** (`literal_family` or `capability`), never a concrete
  model id. Resolving a tier to a model is not your job.
- You have no shell, no credentials, no file access, and no ability to move a
  label, merge a pull request, or start a process.
- At most 4 dispatches in one command, each with a unique `request_id` and a
  unique `idempotency_key`.
- Copy `driver_id`, `epoch` and `phase_attempt` from the capsule's `lease`
  verbatim, and `expected_route_policy_revision` from its
  `route_policy_revision`. A request carrying different values is fenced and
  refused.

Edge cases, and what to do about each:

- If the phase is already well specified and no extra worker would help, reply
  `yield`. Yielding is a real answer, not a failure.
- If the capsule shows a merged or otherwise terminal state, reply `finish`.
- If `stop_requested` or `draining` is true, reply `yield`; every dispatch would
  be refused anyway and asking wastes the turn.
- If `remaining_usd_budget` is 0, reply `yield`; there is no budget to spend.
- If a role you want is missing from `allowed_roles`, do not request it — ask
  for the closest role that is allowed, or `yield`. A request outside the list
  is refused, never substituted.
- If `live_stage_label` disagrees with what the goal implies, an operator has
  moved the issue by hand; trust the label and `yield` rather than fight it.
- Otherwise, if you are unsure, reply `yield`. A wrong dispatch costs a worker;
  a yield costs one cheap turn.

<example>
For a capsule at phase IMPLEMENT with allowed_roles ["explorer", "implementer"],
lease {{"driver_id": "drv-42-a1b2c3d4", "epoch": 3, "phase_attempt": 0}},
route_policy_revision "route-v7", and a goal naming an unfamiliar subsystem, a
good reply is:

{{"kind": "dispatch_workers", "rationale": "the fix touches a subsystem the goal does not describe; map it before writing code", "dispatches": [{{"request_id": "req-a1", "driver_id": "drv-42-a1b2c3d4", "epoch": 3, "phase_attempt": 0, "worker_role": "explorer", "model_requirement": {{"kind": "literal_family", "value": "claude-sonnet"}}, "task_contract": "list the modules that implement chunked upload and how they signal failure", "reason": "the goal names a subsystem the capsule does not describe", "expected_route_policy_revision": "route-v7", "idempotency_key": "8801-e3-implement-explore"}}]}}
</example>

{CAPSULE_OPEN}
{capsule_json}
{CAPSULE_CLOSE}
"""


def extract_command_json(frames: list[dict[str, Any]]) -> str | None:
    """Pull the last JSON object the assistant emitted, or ``None``.

    Deliberately conservative: it takes the *last* balanced JSON object from the
    assistant text, so a model that narrates before answering is tolerated while
    a model that answers with prose only yields ``None`` — which the caller
    treats as a malformed turn and fails closed on, rather than guessing.
    """
    text_parts: list[str] = []
    for frame in frames:
        if frame.get("type") != "assistant":
            continue
        content = frame.get("message", {})
        blocks = content.get("content") if isinstance(content, dict) else None
        for block in blocks or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
    text = "\n".join(text_parts)
    end = text.rfind("}")
    while end != -1:
        start = text.rfind("{", 0, end)
        while start != -1:
            candidate = text[start : end + 1]
            try:
                if isinstance(json.loads(candidate), dict):
                    return candidate
            except json.JSONDecodeError:
                pass
            start = text.rfind("{", 0, start)
        end = text.rfind("}", 0, end)
    return None
