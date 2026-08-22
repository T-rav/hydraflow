"""Shared utilities for phase modules — eliminates duplicated patterns."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Collection,
    Coroutine,
    Generator,
)
from contextlib import asynccontextmanager, contextmanager
from typing import Any, TypeVar

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from exception_classify import (  # noqa: F401
    INFRA_FATAL_EXCEPTIONS,
    is_fatal,
    is_likely_bug,
    reraise_on_credit_or_bug,
)
from harness_insights import FailureCategory, FailureRecord, HarnessInsightStore
from issue_state import issue_state_is_resolved  # noqa: F401
from models import EscalationContext, PipelineStage, PRInfo, ReviewUpdatePayload, Task
from ports import IssueStorePort, PRPort
from state import StateTracker

logger = logging.getLogger("hydraflow.phase_utils")

T = TypeVar("T")
T_Result = TypeVar("T_Result")


@contextmanager
def _sentry_transaction(op: str, name: str) -> Generator[None, None, None]:
    """Transaction-span placeholder around a pipeline phase block.

    Currently a no-op: observability moved to a future SRE agent + New Relic
    (ADR-0118), and no tracing backend is wired. The ``op`` / ``name`` labels
    are retained on the signature so a real span can be threaded back in here
    without touching the phase call sites.

    Usage::

        with _sentry_transaction("pipeline.implement", f"implement:#{issue.id}"):
            result = await self._run_worker(issue)
    """
    yield


async def _fill_pending_slots(
    supply_fn: Callable[[], list[T] | Awaitable[list[T]]],
    worker_fn: Callable[[int, T], Coroutine[Any, Any, T_Result]],
    pending: dict[asyncio.Task[T_Result], int],
    max_concurrent: int,
    worker_id_counter: int,
) -> int:
    """Fill available pool slots from supply_fn, returning updated counter.

    ``supply_fn`` may be sync (returns a list) or async (returns an
    awaitable list). An async supply lets a stage live-pull + gate from
    the store on every refill instead of draining once up front — so a
    long-running worker no longer starves newly-ready work of a free
    slot (#10511, restoring the mid-run refill intent of #10312 for the
    gated path).
    """
    while len(pending) < max_concurrent:
        new_items = supply_fn()
        if inspect.isawaitable(new_items):
            new_items = await new_items
        if not new_items:
            break
        free = max_concurrent - len(pending)
        for item in new_items[:free]:
            task = asyncio.create_task(worker_fn(worker_id_counter, item))
            pending[task] = worker_id_counter
            worker_id_counter += 1
    return worker_id_counter


async def _cancel_remaining(pending: Collection[asyncio.Task[Any]]) -> None:
    """Cancel all tasks in pending and await their completion."""
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def handle_pool_worker_exception(
    exc: BaseException,
    siblings: Collection[asyncio.Task[Any]],
    *,
    log: logging.Logger,
    context: str,
) -> None:
    """Apply the fatal-or-continue policy to one failed worker in a pool.

    Every concurrent worker pool needs the same decision: does this failure
    poison the whole batch, or only its own item?  A fatal exception cancels
    *siblings* and re-raises so the loop above sees it; anything else is
    logged at WARNING against *context* and the batch runs on.

    "Fatal" is :func:`exception_classify.is_fatal` — the same set
    :func:`reraise_on_credit_or_bug` enforces off-pool, so a ``TypeError``
    escalates identically whether or not it happened inside a pool.  Pools
    used to restate that set as a literal tuple and the copy drifted: it
    omitted the likely-bug class, so a real code bug in a pooled worker was
    logged as a transient failure and the cycle reported success (#11618).
    """
    if is_fatal(exc):
        await _cancel_remaining(siblings)
        raise exc
    log.warning("%s: %s", context, exc, exc_info=exc)


async def _process_done_tasks(
    done: set[asyncio.Task[T_Result]],
    pending: dict[asyncio.Task[T_Result], int],
    results: list[T_Result],
) -> None:
    """Process completed tasks: collect results or handle exceptions.

    Fatal exceptions cancel remaining pending tasks and re-raise; non-fatal
    ones are logged at WARNING and the pool continues.  See
    :func:`handle_pool_worker_exception` for what counts as fatal.
    """
    for task in done:
        del pending[task]
        exc = task.exception()
        if exc is None:
            results.append(task.result())
        else:
            await handle_pool_worker_exception(
                exc, pending, log=logger, context="Pool worker failed"
            )


async def _collect_batch_results(
    all_tasks: list[asyncio.Task[T_Result]],
    stop_event: asyncio.Event,
) -> list[T_Result]:
    """Iterate as_completed, collecting results; cancel remainder if stop fires."""
    results: list[T_Result] = []
    for task in asyncio.as_completed(all_tasks):
        results.append(await task)
        if stop_event.is_set():
            for t in all_tasks:
                t.cancel()
            break
    return results


async def run_concurrent_batch(
    items: list[T],
    worker_fn: Callable[[int, T], Coroutine[Any, Any, T_Result]],
    stop_event: asyncio.Event,
) -> list[T_Result]:
    """Run *worker_fn* on each item concurrently, cancelling on stop.

    Creates one task per item, collects results via ``as_completed``,
    and cancels remaining tasks if *stop_event* is set or if this
    coroutine itself is cancelled externally.
    """
    all_tasks = [
        asyncio.create_task(worker_fn(i, item)) for i, item in enumerate(items)
    ]
    try:
        return await _collect_batch_results(all_tasks, stop_event)
    finally:
        for t in all_tasks:
            if not t.done():
                t.cancel()


async def run_refilling_pool(
    supply_fn: Callable[[], list[T] | Awaitable[list[T]]],
    worker_fn: Callable[[int, T], Coroutine[Any, Any, T_Result]],
    max_concurrent: int,
    stop_event: asyncio.Event,
    *,
    poll_interval: float | None = None,
) -> list[T_Result]:
    """Run *worker_fn* in a slot-filling pool, pulling new items as slots free.

    Unlike :func:`run_concurrent_batch` which processes a fixed list,
    this continuously pulls from *supply_fn* whenever a slot opens.
    This ensures no worker capacity sits idle while work is available
    in the queue.

    *supply_fn* should return up to N available items (non-blocking).
    It is called each time a slot frees up to refill the pool.

    *poll_interval* (opt-in): when set to a positive number of seconds, the
    pool wakes at least that often to re-run *supply_fn* into any free slots,
    rather than only waking when an in-flight task completes. This lets work
    enqueued mid-run (e.g. an eager triage→plan handoff) be dispatched into a
    free slot without waiting for a long-running task to finish (issue
    #10296). When ``None`` (the default) the pool blocks on
    :func:`asyncio.wait` until a task completes, preserving the original
    completion-only refill behavior.
    """
    results: list[T_Result] = []
    pending: dict[asyncio.Task[T_Result], int] = {}  # task -> worker id placeholder
    worker_id_counter = 0

    try:
        while not stop_event.is_set():
            worker_id_counter = await _fill_pending_slots(
                supply_fn, worker_fn, pending, max_concurrent, worker_id_counter
            )
            if not pending:
                break
            done, _ = await asyncio.wait(
                pending.keys(),
                timeout=poll_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            await _process_done_tasks(done, pending, results)
    finally:
        await _cancel_remaining(pending)

    return results


def release_batch_in_flight(
    store: IssueStorePort,
    issue_numbers: set[int],
    *,
    expected_stage: str | None = None,
) -> None:
    """Release in-flight protection for a batch of issues.

    Should be called in a ``finally`` block after ``run_concurrent_batch``
    to ensure no orphaned in-flight entries survive if a worker exits
    without reaching ``mark_active`` / ``mark_complete``.
    """
    if expected_stage is None:
        store.release_in_flight(issue_numbers)
    else:
        store.release_in_flight(
            issue_numbers,
            expected_stage=expected_stage,
        )


# ``issue_state_is_resolved`` — the resolved-state predicate — is re-exported
# from ``issue_state`` (see the import block above). The vocabulary lives in
# that zero-dependency leaf so stdlib-only scanners can use it without
# importing the phase stack; ``phase_utils`` re-exports it because phase
# modules (implement_phase, #11457) pin this module as the import surface.


async def escalate_to_hitl(
    state: StateTracker,
    prs: PRPort,
    issue_number: int,
    *,
    cause: str,
    origin_label: str,
    hitl_label: str,
) -> None:
    """Record HITL escalation state and swap labels.

    This is the simple escalation path used by plan, implement, and
    triage phases.  The review phase has a richer variant with event
    publishing and PR comment routing.
    """
    state.set_hitl_origin(issue_number, origin_label)
    state.set_hitl_cause(issue_number, cause)
    state.record_hitl_escalation()
    await prs.swap_pipeline_labels(issue_number, hitl_label)


async def escalate_to_diagnostic(
    state: StateTracker,
    prs: PRPort,
    issue_number: int,
    *,
    context: EscalationContext,
    origin_label: str,
    diagnose_label: str,
) -> None:
    """Route an issue to the diagnostic loop instead of HITL.

    Stores full escalation context, records HITL origin/cause for
    traceability, and swaps labels to *diagnose_label*.
    """
    state.set_escalation_context(issue_number, context)
    state.set_hitl_origin(issue_number, origin_label)
    state.set_hitl_cause(issue_number, context.cause)
    state.record_hitl_escalation()
    await prs.swap_pipeline_labels(issue_number, diagnose_label)


async def park_issue(
    prs: PRPort,
    issue_number: int,
    *,
    parked_label: str,
    reasons: list[str],
) -> None:
    """Park an issue that needs author clarification.

    Swaps pipeline labels to *parked_label* and posts a comment
    asking the author to provide missing information.  Unlike
    ``escalate_to_hitl`` this does **not** record HITL state — the
    issue stays outside the HITL queue.
    """
    await prs.swap_pipeline_labels(issue_number, parked_label)
    note = (
        "## Needs More Information\n\n"
        "This issue doesn't have enough detail for HydraFlow to begin work.\n\n"
        "**Missing:**\n" + "\n".join(f"- {r}" for r in reasons) + "\n\n"
        "Please update the issue with more context and re-apply "
        "the `hydraflow-find` label when ready.\n\n"
        "---\n*Generated by HydraFlow Triage*"
    )
    await prs.post_comment(issue_number, note)


def parse_memory_suggestion(transcript: str) -> dict[str, str] | None:
    """Parse a MEMORY_SUGGESTION block in tribal format.

    Returns a dict with ``principle``, ``rationale``, ``failure_mode``,
    and ``scope`` keys, or ``None`` if the block is missing or any
    required field is empty.
    """
    import re as _re  # noqa: PLC0415

    pattern = r"MEMORY_SUGGESTION_START\s*\n(.*?)\nMEMORY_SUGGESTION_END"
    match = _re.search(pattern, transcript, _re.DOTALL)
    if not match:
        return None

    block = match.group(1)
    fields = ("principle", "rationale", "failure_mode", "scope")
    result: dict[str, str] = dict.fromkeys(fields, "")

    for line in block.splitlines():
        stripped = line.strip()
        for key in fields:
            prefix = f"{key}:"
            if stripped.startswith(prefix):
                result[key] = stripped[len(prefix) :].strip()
                break

    if not all(result[k] for k in fields):
        return None
    return result


async def file_memory_suggestion(
    transcript: str,
    source: str,
    reference: str,
    config: HydraFlowConfig,
) -> None:
    """Parse and store a tribal-memory suggestion from an agent transcript.

    Writes to local JSONL storage (items.jsonl). No Hindsight writes.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    parsed = parse_memory_suggestion(transcript)
    if not parsed:
        return

    from models import TribalMemory  # noqa: PLC0415

    def _next_item_id() -> str:
        import uuid as _uuid  # noqa: PLC0415

        return f"mem-{_uuid.uuid4().hex[:8]}"

    try:
        mem = TribalMemory(
            principle=parsed["principle"],
            rationale=parsed["rationale"],
            failure_mode=parsed["failure_mode"],
            scope=parsed["scope"],
            id=_next_item_id(),
            source=source,
            created_at=datetime.now(UTC).isoformat(),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Tribal memory failed schema validation: %s", reference)
        return

    try:
        items_path = config.data_path("memory", "items.jsonl")
        items_path.parent.mkdir(parents=True, exist_ok=True)
        with items_path.open("a") as f:
            f.write(mem.model_dump_json() + "\n")
    except OSError:
        logger.warning("Failed to write tribal memory to JSONL", exc_info=True)
        return

    logger.info("Stored tribal memory %s scope=%s", mem.id, mem.scope)


async def safe_file_memory_suggestion(
    transcript: str,
    source: str,
    reference: str,
    config: HydraFlowConfig,
) -> None:
    """File a memory suggestion, swallowing and logging exceptions."""
    try:
        await file_memory_suggestion(
            transcript,
            source,
            reference,
            config,
        )
    except Exception:
        logger.exception(
            "Failed to file memory suggestion for %s",
            reference,
        )


def record_harness_failure(
    harness_insights: HarnessInsightStore | None,
    issue_number: int,
    category: FailureCategory,
    details: str,
    *,
    stage: PipelineStage,
    pr_number: int = 0,
) -> None:
    """Record a failure to the harness insight store (non-blocking).

    Shared across plan, implement, and review phases.  Silently skips
    when *harness_insights* is ``None`` and suppresses exceptions so
    insight recording never interrupts the pipeline.
    """
    if harness_insights is None:
        return
    try:
        from harness_insights import extract_subcategories  # noqa: PLC0415

        record = FailureRecord(
            issue_number=issue_number,
            pr_number=pr_number,
            category=category,
            subcategories=extract_subcategories(details),
            details=details,
            stage=stage,
        )
        harness_insights.append_failure(record)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to record harness failure for issue #%d",
            issue_number,
            exc_info=True,
        )


@asynccontextmanager
async def store_lifecycle(
    store: IssueStorePort,
    issue_number: int,
    stage: str,
) -> AsyncGenerator[None, None]:
    """Mark an issue active on enter and complete on exit.

    Args:
        store: The issue store that tracks active/complete status.
        issue_number: GitHub issue number to mark.
        stage: Pipeline stage name (e.g. ``"plan"``, ``"review"``). Either
            the internal ``IssueStoreStage`` value or its dashboard-facing
            display name (``"implement"`` for READY) is accepted — the store
            normalizes via ``issue_store.resolve_issue_store_stage`` so the
            active/throughput counters key on one vocabulary (#11551).

    Usage::

        async with store_lifecycle(store, issue.number, "plan"):
            ...  # do work
    """
    store.mark_active(issue_number, stage)
    try:
        yield
    finally:
        store.mark_complete(issue_number)


async def publish_review_status(
    bus: EventBus, pr: PRInfo, worker_id: int, status: str
) -> None:
    """Emit a REVIEW_UPDATE event with the given status."""
    await bus.publish(
        HydraFlowEvent(
            type=EventType.REVIEW_UPDATE,
            data=ReviewUpdatePayload(
                pr=pr.number,
                issue=pr.issue_number,
                worker=worker_id,
                status=status,
                role="reviewer",
            ),
        )
    )


def log_exception_with_bug_classification(
    log: logging.Logger,
    exc: BaseException,
    context: str,
) -> None:
    """Log *exc* at the appropriate severity based on :func:`is_likely_bug`.

    If the exception is likely a code bug, log at ``CRITICAL`` with a
    "needs code fix" hint; otherwise log at ``WARNING`` with ``exc_info``.
    """
    exc_type_name = type(exc).__name__
    if is_likely_bug(exc):
        log.critical(
            "%s — likely bug (%s), needs code fix",
            context,
            exc_type_name,
            exc_info=True,
        )
    else:
        log.warning("%s — %s", context, exc_type_name, exc_info=True)


async def run_with_fatal_guard(
    coro: Coroutine[Any, Any, T],
    *,
    on_failure: Callable[[str], T],
    context: str,
    log: logging.Logger,
) -> T:
    """Await *coro*, re-raising fatal errors and classifying the rest.

    Infrastructure-fatal errors (:data:`~exception_classify.INFRA_FATAL_EXCEPTIONS`)
    propagate immediately.  All other exceptions — likely bugs included — are
    logged via :func:`log_exception_with_bug_classification` (which escalates a
    likely bug to CRITICAL) and ``on_failure(exc_type_name)`` is returned as the
    result.  That classify-and-degrade contract is deliberate here: unlike a
    worker pool, this guard hands the caller a substitute result rather than
    dropping the failure on the floor.
    """
    try:
        return await coro
    except INFRA_FATAL_EXCEPTIONS:
        raise
    except Exception as exc:
        log_exception_with_bug_classification(log, exc, context)
        return on_failure(type(exc).__name__)


class MemorySuggester:
    """Pre-bound callable for :func:`safe_file_memory_suggestion`.

    Stores config + hindsight client + judge so call sites only need to pass
    (transcript, source, reference).

    Usage::

        suggest = MemorySuggester(config)
        await suggest(transcript, "planner", f"issue #{issue.id}")
    """

    __slots__ = ("_config",)

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config

    async def __call__(self, transcript: str, source: str, reference: str) -> None:
        await safe_file_memory_suggestion(
            transcript,
            source,
            reference,
            self._config,
        )


class PipelineEscalator:
    """Bundles ``escalate_to_hitl`` + ``enqueue_transition`` + ``record_harness_failure``.

    The plan and implement phases repeat this trio at every escalation
    site.  This helper encapsulates the three calls so each call site
    collapses to a single ``await escalator(...)`` invocation.

    Usage::

        escalator = PipelineEscalator(
            state, prs, store, harness_insights,
            origin_label=config.planner_label[0],
            hitl_label=config.hitl_label[0],
            stage=PipelineStage.PLAN,
        )
        await escalator(issue, cause="...", details="...", category=FailureCategory.PLAN_VALIDATION)
    """

    __slots__ = (
        "_state",
        "_prs",
        "_store",
        "_harness_insights",
        "_origin_label",
        "_hitl_label",
        "_diagnose_label",
        "_stage",
    )

    def __init__(
        self,
        state: StateTracker,
        prs: PRPort,
        store: IssueStorePort,
        harness_insights: HarnessInsightStore | None,
        *,
        origin_label: str,
        hitl_label: str,
        diagnose_label: str = "",
        stage: PipelineStage,
    ) -> None:
        self._state = state
        self._prs = prs
        self._store = store
        self._harness_insights = harness_insights
        self._origin_label = origin_label
        self._hitl_label = hitl_label
        self._diagnose_label = diagnose_label
        self._stage = stage

    async def __call__(
        self,
        issue: Task,
        *,
        cause: str,
        details: str,
        category: FailureCategory,
        context: EscalationContext | None = None,
    ) -> None:
        """Escalate *issue* to diagnostic (or HITL), enqueue transition, and record failure."""
        issue_number = issue.id
        if context is None:
            context = EscalationContext(cause=cause, origin_phase=self._stage.value)
        try:
            await escalate_to_diagnostic(
                self._state,
                self._prs,
                issue_number,
                context=context,
                origin_label=self._origin_label,
                diagnose_label=self._diagnose_label,
            )
        except Exception:
            logger.error(
                "Escalation to diagnostic failed for issue #%d — attempting direct label swap to HITL",
                issue_number,
                exc_info=True,
            )
            # Best-effort fallback: try label swap directly so the issue
            # doesn't get stuck in its current pipeline stage forever.
            try:
                await self._prs.swap_pipeline_labels(issue_number, self._hitl_label)
            except Exception:
                logger.error(
                    "Fallback label swap also failed for issue #%d — issue may be stuck",
                    issue_number,
                    exc_info=True,
                )
        self._store.enqueue_transition(issue, "diagnose")
        record_harness_failure(
            self._harness_insights,
            issue_number,
            category,
            details,
            stage=self._stage,
        )
