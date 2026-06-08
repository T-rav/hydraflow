"""LiveCorpusReplayLoop — read shadow corpus, diff vs fakes (Phase 2 of #8786).

Closes the value-level drift detection half of the v2 trust pattern. Each
tick:

1. Enumerate fresh samples from ``ShadowCorpus``.
2. For each sample with a registered dispatcher, invoke the matching
   fake-adapter method with the sampled input.
3. Diff the fake's normalized output against the sample's normalized
   stored output.
4. On drift, file a single ``hydraflow-find`` + ``shadow-drift`` issue
   per loop tick (dedup'd on drift signature) so the existing IMPL
   pipeline picks it up — no human escalation surface.

Samples whose ``(adapter, command, args)`` shape has no registered
dispatcher are silently skipped this tick. The dispatcher registry is
populated by follow-up PRs as call shapes are wired through Pydantic
``contracts.shapes`` models — Phase 2 ships the loop + an empty
registry + one demonstration dispatcher (``gh pr view``) to prove the
contract.

The 3-attempt escalation chain + auto-agent dispatch live in Phase 3.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001
from state import StateTracker  # noqa: TCH001

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from contracts.shadow import ShadowCorpus, ShadowSample
    from dedup_store import DedupStore
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.live_corpus_replay_loop")


# A dispatcher takes one ShadowSample and returns the fake adapter's
# "equivalent output" as a dict — the same shape the recorder captured.
# Returns None if the fake has no opinion on this sample (loop logs +
# skips). Raises on internal errors — the loop catches and reports them
# as drift attribute "dispatcher_error" so they surface, not silenced.
Dispatcher = Callable[["ShadowSample"], Awaitable[dict[str, Any] | None]]

# Registry keyed on (adapter, command). Subkey on a frozenset of arg
# prefix tokens lets multiple ``gh pr view`` shapes share one dispatcher
# (the dispatcher itself can branch on ``sample.args``).
DispatcherKey = tuple[str, str]


class LiveCorpusReplayLoop(BaseBackgroundLoop):
    """Periodically diff shadow corpus samples vs fake-adapter outputs."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        corpus: ShadowCorpus,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
        state: StateTracker | None = None,
        dispatchers: dict[DispatcherKey, Dispatcher] | None = None,
    ) -> None:
        super().__init__(
            worker_name="live_corpus_replay",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._corpus = corpus
        self._pr = pr_manager
        self._dedup = dedup
        self._state = state
        self._dispatchers: dict[DispatcherKey, Dispatcher] = dict(dispatchers or {})

    def _get_default_interval(self) -> int:
        return self._config.live_corpus_replay_interval

    def register(self, adapter: str, command: str, fn: Dispatcher) -> None:
        """Register a dispatcher for ``(adapter, command)``.

        The dispatcher receives the full ShadowSample so it can branch on
        ``args`` (e.g. ``gh pr view`` covers many ``--json`` field sets).
        """
        self._dispatchers[(adapter, command)] = fn

    def registered_shapes(self) -> set[DispatcherKey]:
        """Return the set of ``(adapter, command)`` pairs covered by this loop.

        Used by external retirement-audit code (Phase 6 of #8786) — when
        a hand-authored baseline cassette's shape is covered by a live
        dispatcher, the cassette becomes a retirement candidate.
        """
        return set(self._dispatchers.keys())

    async def _do_work(self) -> WorkCycleResult:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        samples = self._corpus.list()
        compared = 0
        skipped_no_dispatcher = 0
        drifted: list[tuple[Path, str]] = []  # (path, signature)
        errors = 0

        for path in samples:
            try:
                sample = self._corpus.load(path)
            except (OSError, ValueError) as exc:
                logger.warning("could not load shadow sample %s: %s", path, exc)
                errors += 1
                continue

            dispatcher = self._dispatchers.get((sample.adapter, sample.command))
            if dispatcher is None:
                skipped_no_dispatcher += 1
                continue

            try:
                fake_output = await dispatcher(sample)
            except Exception:  # noqa: BLE001 — replay must continue on dispatcher error
                logger.exception(
                    "dispatcher raised for %s/%s args=%s",
                    sample.adapter,
                    sample.command,
                    sample.args,
                )
                errors += 1
                continue

            compared += 1
            if fake_output is None:
                continue

            signature = _drift_signature(sample, fake_output)
            if signature is not None:
                drifted.append((path, signature))

        filed_issue: int | None = None
        escalated_issue: int | None = None
        escalated_signatures: list[str] = []

        if drifted:
            # Increment per-signature attempt counters and identify any
            # that have hit the escalation threshold.
            if self._state is not None:
                threshold = self._config.live_corpus_max_drift_attempts
                for _path, sig in drifted:
                    attempts = self._state.inc_live_corpus_drift_attempts(sig)
                    if attempts >= threshold and sig not in escalated_signatures:
                        escalated_signatures.append(sig)

            # Keep ONE open ``shadow-drift`` rollup issue and rewrite its body
            # as the diverged set changes — instead of filing a brand-new issue
            # for every changed signature set (which piled up #9258..#9335).
            filed_issue = await self._upsert_drift_rollup(drifted)

            # If any signature reached the threshold, keep a single open
            # ``shadow-drift-stuck`` escalation issue routed to the auto-agent
            # preflight loop via the ``hitl-escalation`` label.
            if escalated_signatures:
                escalated_issue = await self._upsert_escalation(escalated_signatures)
        # Clean tick: the fakes caught up. Close the open rollup + escalation
        # issues (their job is done) and clear all per-signature counters so a
        # future re-occurrence starts fresh.
        elif self._state is not None:
            await self._resolve_open_issues()
            self._state.clear_live_corpus_drift_attempts()

        return {
            "status": "ok",
            "compared": compared,
            "skipped_no_dispatcher": skipped_no_dispatcher,
            "drifted": len(drifted),
            "errors": errors,
            "filed_issue": filed_issue,
            "escalated_issue": escalated_issue,
            "escalated_signatures": len(escalated_signatures),
        }

    async def _upsert_drift_rollup(self, drifted: list[tuple[Path, str]]) -> int | None:
        """Maintain a single open ``shadow-drift`` issue for the fleet.

        With state: create the issue once, then ``update_issue_body`` in place
        whenever the diverged set changes (skipping a no-op write when it
        hasn't). Without state (unit tests): preserve the original
        dedup-store-gated single-file behaviour. Returns the rollup issue
        number, or ``0``/``None`` when nothing could be filed.
        """
        current_hash = _fleet_dedup_key(drifted)

        if self._state is not None:
            rollup = self._state.get_live_corpus_drift_rollup()
            if rollup and rollup["issue_number"]:
                issue_number = rollup["issue_number"]
                if rollup["signature_hash"] == current_hash:
                    # Same diverged set as last tick — no GitHub write needed.
                    return None
                await self._pr.update_issue_body(
                    issue_number, self._drift_body(drifted)
                )
                self._state.set_live_corpus_drift_rollup(
                    issue_number=issue_number, signature_hash=current_hash
                )
                return issue_number
            filed = await self._file_drift_issue(drifted)
            if filed and filed != 0:
                self._state.set_live_corpus_drift_rollup(
                    issue_number=filed, signature_hash=current_hash
                )
            else:
                # create_issue 0-sentinel: gh failed. Persist nothing so the
                # next tick retries the create.
                logger.warning(
                    "live_corpus_replay: create_issue returned 0 (sentinel) "
                    "for drift rollup; will retry next cycle",
                )
            return filed

        # State-less path (unit tests): original dedup-store gate.
        seen = self._dedup.get()
        if current_hash in seen:
            return None
        filed = await self._file_drift_issue(drifted)
        if filed == 0:
            logger.warning(
                "live_corpus_replay: create_issue returned 0 (sentinel) for "
                "drift issue; skipping dedup, will retry next cycle",
            )
            return filed
        seen.add(current_hash)
        self._dedup.set_all(seen)
        return filed

    async def _upsert_escalation(self, signatures: list[str]) -> int | None:
        """Keep a single open ``shadow-drift-stuck`` escalation issue."""
        if self._state is not None:
            existing = self._state.get_live_corpus_escalation_issue()
            if existing:
                return existing
            filed = await self._file_escalation_issue(signatures)
            if filed and filed != 0:
                self._state.set_live_corpus_escalation_issue(filed)
            return filed
        return await self._file_escalation_issue(signatures)

    async def _resolve_open_issues(self) -> None:
        """Close the open rollup + escalation issues on a clean (no-drift) tick."""
        if self._state is None:
            return
        rollup = self._state.get_live_corpus_drift_rollup()
        if rollup and rollup["issue_number"]:
            await self._pr.close_issue(rollup["issue_number"])
            self._state.clear_live_corpus_drift_rollup()
        escalation = self._state.get_live_corpus_escalation_issue()
        if escalation:
            await self._pr.close_issue(escalation)
            self._state.clear_live_corpus_escalation_issue()

    async def _file_escalation_issue(self, signatures: list[str]) -> int:
        """File a ``hitl-escalation`` issue when drift signatures exhaust
        the loop's own retry budget.

        Routed via the existing ``hitl-escalation`` label to the
        ``AutoAgentPreflightLoop`` — that loop runs its OWN 3-attempt
        cycle (auto-agent IMPL pipeline) before labeling
        ``human-required``. The combined autonomous-attempt budget is
        ``live_corpus_max_drift_attempts × auto_agent_max_attempts``.
        """
        labels = ["hitl-escalation", "shadow-drift-stuck"]
        title = (
            f"Shadow drift stuck: {len(signatures)} signature(s) survived "
            f"{self._config.live_corpus_max_drift_attempts} tick(s) without repair"
        )
        sig_lines = "\n".join(f"- `{s[:12]}`" for s in signatures[:50])
        body = (
            f"## Drift survived the LiveCorpusReplayLoop retry budget\n\n"
            f"After {self._config.live_corpus_max_drift_attempts} consecutive "
            f"ticks of detecting the same drift signature(s) without the "
            f"earlier `hydraflow-find` repair PR landing, the loop escalates "
            f"to `hitl-escalation` so `AutoAgentPreflightLoop` runs its own "
            f"attempts.\n\n"
            f"### Stuck signatures\n\n{sig_lines}\n\n"
            f"### Repair path\n\n"
            f"The auto-agent preflight loop will pick this up and run "
            f"`auto_agent_max_attempts` IMPL attempts before adding "
            f"`human-required`. Closing this issue clears all per-signature "
            f"counters on the next clean tick."
        )
        return await self._pr.create_issue(
            title=title,
            body=body,
            labels=labels,
        )

    @staticmethod
    def _drift_title(drifted: list[tuple[Path, str]]) -> str:
        return (
            f"Shadow drift: {len(drifted)} fake-adapter output(s) diverged "
            f"from live samples"
        )

    @staticmethod
    def _drift_body(drifted: list[tuple[Path, str]]) -> str:
        body_lines = [
            "## Shadow corpus drift",
            "",
            "`LiveCorpusReplayLoop` compared live-recorded subprocess outputs "
            "against fake-adapter outputs and detected divergence.",
            "",
            "_This is a rolling rollup: the loop keeps a single open "
            "`shadow-drift` issue and rewrites this body as the diverged set "
            "changes, then closes the issue automatically on the first clean "
            "tick (no drift)._",
            "",
            "### Drifted samples",
            "",
        ]
        for path, sig in drifted[:50]:  # cap body length
            body_lines.append(f"- `{path.name}` — signature `{sig[:12]}`")
        body_lines.extend(
            [
                "",
                "**Repair path.** The auto-agent should pick this up via the "
                "`hydraflow-find` label, regenerate the affected fake method to "
                "match the live sample, and open a PR. See #8786 (Phase 3) for "
                "the full auto-repair chain.",
            ]
        )
        return "\n".join(body_lines)

    async def _file_drift_issue(self, drifted: list[tuple[Path, str]]) -> int:
        """File a single hydraflow-find issue covering all drift this tick."""
        return await self._pr.create_issue(
            title=self._drift_title(drifted),
            body=self._drift_body(drifted),
            labels=["hydraflow-find", "shadow-drift"],
        )


def _canonicalize(value: Any) -> Any:
    """Stable JSON-canonical form. Sort dict keys; preserve list order."""
    if isinstance(value, dict):
        return {k: _canonicalize(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(v) for v in value]
    return value


def _drift_signature(sample: ShadowSample, fake_output: dict[str, Any]) -> str | None:
    """Return a stable signature when sample and fake diverge, else None.

    Compares the parsed stdout (if JSON) against ``fake_output``. For
    non-JSON stdout, falls back to a literal string compare.
    """
    try:
        sample_value: Any = json.loads(sample.stdout) if sample.stdout else None
    except (TypeError, ValueError):
        sample_value = sample.stdout
    if _canonicalize(sample_value) == _canonicalize(fake_output):
        return None
    blob = json.dumps(
        {
            "adapter": sample.adapter,
            "command": sample.command,
            "args": sample.args,
            "sample": _canonicalize(sample_value),
            "fake": _canonicalize(fake_output),
        },
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _fleet_dedup_key(drifted: list[tuple[Path, str]]) -> str:
    """Stable dedup key across all drifts in this tick."""
    payload = {"signatures": sorted(sig for _path, sig in drifted)}
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
