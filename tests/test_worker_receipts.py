"""The receipt vocabulary the three brokered actuators share (#11718).

:mod:`worker_receipts` was extracted by #11543 so the Plan (#11541), Implement
(#11542) and Review actuators could not drift on what a receipt means — and
then shipped with no test file at all, which left the consistency it exists to
enforce entirely unpinned. Every one of these receipts is published verbatim
into the worker tree (:func:`fable_director._receipt_row`), which is where
ADR-0137 B5's bar is read from, so a fabricated decision id, an outcome that
claims a route was selected when none resolved, or a cost term silently dropped
corrupts the evidence the canary is judged by rather than merely a log line.

The claims pinned here, each one a mutation that previously survived the whole
suite:

* a blank decision names **no** id, **no** rule, **no** source and **no** served
  model, and its outcome is a rejection — not a selection;
* every field of :class:`plan_broker.PlanRouteDecision` is set deliberately, so
  a field added upstream cannot silently take a default here;
* an unmeasurable or unpriced spend is exactly ``0.0`` — never a guess;
* all four token buckets the seam reports reach the pricing table, in the right
  positions, so no term can be dropped without a red test;
* a content address is the **full** digest of the output's UTF-8 bytes.

Pure module, pure tests: the pricing table's own asset is the only I/O, and the
recording double that stands in for it mirrors the real signature (a fidelity
:func:`inspect.signature` check keeps that honest rather than aspirational).
"""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import fields
from typing import Any

import pytest
from pydantic import ValidationError

import worker_receipts
from driver_contracts import (
    ModelRequirement,
    ModelRequirementKind,
    ReceiptStatus,
    RejectionReason,
    WorkerReceipt,
    WorkerRole,
)
from model_pricing import ModelPricingTable, ModelRate
from plan_broker import (
    PLAN_TIER_CATALOG_REVISION,
    PlanRouteDecision,
    PlanRouteOutcome,
    PlanRouteReason,
    PlanRouteRule,
    PlanRouteSource,
)
from worker_receipts import (
    artifact_digest,
    estimate_worker_cost,
    unresolved_decision,
)

ROUTE_REVISION = "route-policy-test-1"

#: Every field of the blank decision, named explicitly. Two tests read this:
#: one compares the built record against it, the other asserts it covers the
#: dataclass exhaustively — so neither a changed value nor a newly added field
#: silently taking a default can pass.
EXPECTED_BLANK: dict[str, Any] = {
    "decision_id": "",
    "outcome": PlanRouteOutcome.REJECTED,
    "rule": PlanRouteRule.NONE_MATCHED,
    "source": PlanRouteSource.NONE,
    "reason": PlanRouteReason.NONE,
    "catalog_revision": PLAN_TIER_CATALOG_REVISION,
    "route_policy_revision": ROUTE_REVISION,
    "worker_role": "",
    "phase": "",
    "requirement_kind": "",
    "requirement_value": "",
    "served_model": "",
}

# Distinct, non-round rates per bucket. Distinctness is load-bearing: with
# equal rates a swapped or dropped argument would produce the same number and
# the term-coverage tests below would pass vacuously.
FAKE_RATE = ModelRate(
    input_cost_per_million=3.37,
    output_cost_per_million=17.11,
    cache_write_cost_per_million=61.29,
    cache_read_cost_per_million=101.53,
    input_includes_cache=False,
)

# Distinct, non-round counts, for the same reason.
FULL_USAGE: dict[str, Any] = {
    "input_tokens": 1301,
    "output_tokens": 227,
    "cache_creation_input_tokens": 4093,
    "cache_read_input_tokens": 8191,
}

#: The seam's token buckets -> the pricing table's own argument name for each.
#: The two vocabularies differ ("cache_creation_input_tokens" on the wire,
#: "cache_write_tokens" in the table), which is exactly where a wrong-key or
#: swapped-position mutation hides.
BUCKET_TO_RATE_ARG = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_creation_input_tokens": "cache_write_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
}

BUCKETS = tuple(BUCKET_TO_RATE_ARG)

#: A model the shipped pricing asset actually prices, for the tests that must
#: run against the real table rather than a double.
PRICED_MODEL = "claude-sonnet-4-20250514"


class RecordingPricingTable:
    """A pricing table that records the call and then prices it for real.

    Mirrors :meth:`model_pricing.ModelPricingTable.estimate_cost` exactly;
    ``test_the_recording_double_matches_the_real_pricing_signature`` fails if
    that stops being true, so a signature change upstream cannot leave these
    tests asserting against a shape nothing calls any more.
    """

    def __init__(self, rate: ModelRate | None) -> None:
        self.rate = rate
        self.calls: list[dict[str, Any]] = []

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        *,
        input_includes_cache: bool | None = None,
    ) -> float | None:
        self.calls.append(
            {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_write_tokens": cache_write_tokens,
                "cache_read_tokens": cache_read_tokens,
                "input_includes_cache": input_includes_cache,
            }
        )
        if self.rate is None:
            return None
        return self.rate.estimate_cost(
            input_tokens,
            output_tokens,
            cache_write_tokens,
            cache_read_tokens,
            input_includes_cache=input_includes_cache,
        )


def refusal_receipt(*, route_policy_revision: str, **overrides: Any) -> WorkerReceipt:
    """The refusal receipt shape all three actuators build from a blank decision.

    The requirement is a **literal family** rather than a capability class on
    purpose: ``ModelRequirement.satisfied_by`` returns ``True`` for every
    capability class, so a capability-shaped receipt would exercise the
    model-honesty validator vacuously — it cannot fail. A literal family is the
    case the validator exists for.
    """
    return WorkerReceipt(
        request_id="req-1",
        idempotency_key="idem-1",
        status=ReceiptStatus.REJECTED,
        reason_code=RejectionReason.ROUTE_UNAVAILABLE,
        worker_role=WorkerRole.PLANNER,
        requested_model=ModelRequirement(
            kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-sonnet"
        ),
        route_policy_revision=route_policy_revision,
        output_contract_ok=False,
        **overrides,
    )


@pytest.fixture
def pricing(monkeypatch: pytest.MonkeyPatch) -> RecordingPricingTable:
    """Stand the recording table in for the lazily imported real one.

    ``estimate_worker_cost`` imports ``load_pricing`` from ``model_pricing``
    inside the call, so the module attribute is the live binding — patching it
    here is what the function actually resolves. Every test using this fixture
    asserts ``pricing.calls`` is non-empty, because a patch that bound the
    wrong module would otherwise pass silently.
    """
    table = RecordingPricingTable(FAKE_RATE)
    monkeypatch.setattr("model_pricing.load_pricing", lambda *a, **k: table)
    return table


# -- the shared surface ----------------------------------------------------


def test_the_module_exports_exactly_the_three_shared_helpers() -> None:
    """The export surface is the contract the three actuators import against.

    Guarded in both directions: a helper dropped from ``__all__`` and a private
    one added to it are equally a change to what "one vocabulary" means.
    """
    assert set(worker_receipts.__all__) == {
        "artifact_digest",
        "estimate_worker_cost",
        "unresolved_decision",
    }
    assert list(worker_receipts.__all__) == sorted(worker_receipts.__all__)
    for name in worker_receipts.__all__:
        assert callable(getattr(worker_receipts, name))


def test_the_pricing_table_is_not_bound_at_module_import() -> None:
    """``load_pricing`` is imported inside the call, and must stay there.

    The module's own docstring claims "no I/O beyond the pricing table's own
    lazy load". A module-level binding would move that read to import time and
    make every consumer of the receipt vocabulary pay for the pricing asset —
    and would also silently move which object ``monkeypatch`` must target,
    which is how a cost test goes vacuous.
    """
    assert not hasattr(worker_receipts, "load_pricing")


# -- unresolved_decision ---------------------------------------------------


def test_the_blank_decision_is_exactly_the_record_with_nothing_invented() -> None:
    assert unresolved_decision(ROUTE_REVISION) == PlanRouteDecision(**EXPECTED_BLANK)


def test_every_field_of_the_decision_record_is_pinned_by_this_module() -> None:
    """No field of ``PlanRouteDecision`` may default silently in a receipt.

    The guard runs in the direction that fails quietly: a field added upstream
    would take its dataclass default in ``unresolved_decision`` without any
    test noticing, and would then be published into a canary's evidence as a
    value nobody chose. Widening this set is the deliberate act of choosing one.
    """
    assert {field.name for field in fields(PlanRouteDecision)} == set(EXPECTED_BLANK)


def test_the_blank_decision_outcome_is_a_rejection_never_a_selection() -> None:
    """The single most damaging flip: a receipt claiming a route was selected.

    Asserted three ways because each is separately readable downstream —
    the enum member, the ``selected`` property the actuators branch on, and the
    string ``fable_director`` publishes into the worker tree.
    """
    decision = unresolved_decision(ROUTE_REVISION)

    assert decision.outcome is PlanRouteOutcome.REJECTED
    assert decision.outcome is not PlanRouteOutcome.SELECTED
    assert decision.selected is False
    assert decision.explain()["outcome"] == "rejected"


@pytest.mark.parametrize("outcome", [PlanRouteOutcome.SELECTED, PlanRouteOutcome.HELD])
def test_no_other_outcome_member_can_stand_for_an_unresolved_route(
    outcome: PlanRouteOutcome,
) -> None:
    """``HELD`` is as wrong as ``SELECTED`` here, and for a different reason.

    A hold is retryable — it sends an operator to fix a credential. Nothing
    resolved at all, so neither disposition describes it.
    """
    assert unresolved_decision(ROUTE_REVISION).outcome is not outcome


def test_the_decision_id_is_empty_rather_than_a_fabricated_one() -> None:
    """An id is a content address of a resolution. None ran, so there is none.

    ``fable_director._receipt_row`` publishes this as ``route_decision_id``;
    any placeholder there is a join key pointing at a decision that never
    existed.
    """
    decision = unresolved_decision(ROUTE_REVISION)

    assert decision.decision_id == ""
    assert decision.explain()["decision_id"] == ""


def test_no_rule_source_reason_or_served_model_is_invented() -> None:
    decision = unresolved_decision(ROUTE_REVISION)

    assert decision.rule is PlanRouteRule.NONE_MATCHED
    assert decision.source is PlanRouteSource.NONE
    assert decision.reason is PlanRouteReason.NONE
    assert decision.served_model == ""


def test_no_requirement_or_boundary_detail_is_invented() -> None:
    decision = unresolved_decision(ROUTE_REVISION)

    assert decision.worker_role == ""
    assert decision.phase == ""
    assert decision.requirement_kind == ""
    assert decision.requirement_value == ""


def test_the_catalog_revision_is_the_live_one_not_a_literal() -> None:
    """The revision a decision is replayed against must be the running one."""
    assert unresolved_decision(ROUTE_REVISION).catalog_revision == (
        PLAN_TIER_CATALOG_REVISION
    )
    assert PLAN_TIER_CATALOG_REVISION.startswith("sha256:")


@pytest.mark.parametrize("revision", ["route-a", "route-b", "sha256:deadbeef"])
def test_the_route_policy_revision_is_the_caller_s_verbatim(revision: str) -> None:
    """The one fact a blank decision carries — and a receipt joins on it."""
    assert unresolved_decision(revision).route_policy_revision == revision


def test_a_blank_decision_carries_a_refusal_receipt_that_validates() -> None:
    """The shape all three actuators build from it: a refusal naming no model.

    ``WorkerReceipt``'s validator is what makes "a refusal names no served
    model" enforceable, so this pins that the blank decision's fields are
    admissible to it rather than merely well-named.
    """
    decision = unresolved_decision(ROUTE_REVISION)

    receipt = refusal_receipt(route_policy_revision=decision.route_policy_revision)

    assert receipt.route_policy_revision == ROUTE_REVISION
    assert decision.served_model == ""
    assert receipt.served_model is None


def test_the_receipt_validator_rejects_a_refusal_that_names_a_served_model() -> None:
    """The other direction: "a refusal names no served model" is enforced.

    Without this, the test above only observes that nothing was passed — it
    would pass just as happily against a model with no validator at all. This
    is what makes the omission load-bearing rather than conventional.
    """
    with pytest.raises(ValidationError):
        refusal_receipt(route_policy_revision=ROUTE_REVISION, served_model="glm-4.6")


# -- estimate_worker_cost --------------------------------------------------


@pytest.mark.parametrize(
    "usage",
    [None, "", "usage", 0, 12, [], ["input_tokens"], (), object(), b"{}"],
    ids=[
        "none",
        "empty-str",
        "str",
        "zero",
        "int",
        "empty-list",
        "list",
        "tuple",
        "object",
        "bytes",
    ],
)
def test_usage_the_seam_did_not_report_costs_exactly_zero(usage: object) -> None:
    """Not a small number, not a plausible one — zero.

    ADR-0137 B5's bar reads "100% of accepted workers carry lineage, cost and
    effective-route receipts". Any non-zero placeholder satisfies its letter
    with a number nobody measured, which is the failure the module's own
    docstring forbids.
    """
    cost = estimate_worker_cost(PRICED_MODEL, usage)

    assert cost == 0.0
    assert isinstance(cost, float)


def test_a_dict_usage_is_actually_priced_rather_than_short_circuited(
    pricing: RecordingPricingTable,
) -> None:
    """The other direction of the guard above: a dict must reach the table."""
    cost = estimate_worker_cost(PRICED_MODEL, FULL_USAGE)

    assert pricing.calls, "the pricing table was never consulted"
    assert cost > 0.0


def test_all_four_token_buckets_reach_the_pricing_table_in_their_own_slots(
    pricing: RecordingPricingTable,
) -> None:
    """Every reported bucket, in the right position, with nothing dropped.

    Written as one whole-call equality rather than four ``in`` checks so that a
    dropped term, a swapped pair and a bucket read under the wrong key all
    redden — the silent-drop direction is the dangerous one here, because a
    missing argument takes a ``0`` default and merely understates cost.
    """
    estimate_worker_cost(PRICED_MODEL, FULL_USAGE)

    assert pricing.calls == [
        {
            "model": PRICED_MODEL,
            "input_tokens": 1301,
            "output_tokens": 227,
            "cache_write_tokens": 4093,
            "cache_read_tokens": 8191,
            "input_includes_cache": None,
        }
    ]


@pytest.mark.parametrize("bucket", BUCKETS)
def test_zeroing_any_one_bucket_changes_the_cost(
    bucket: str, pricing: RecordingPricingTable
) -> None:
    """Each bucket is load-bearing arithmetic, not decoration.

    This holds even if the call is rewritten to keyword arguments, so it kills
    a dropped term independently of the call-shape assertion above.
    """
    without = dict(FULL_USAGE) | {bucket: 0}

    full_cost = estimate_worker_cost(PRICED_MODEL, FULL_USAGE)
    reduced_cost = estimate_worker_cost(PRICED_MODEL, without)

    assert pricing.calls, "the pricing table was never consulted"
    assert reduced_cost < full_cost


def test_the_cost_is_the_pricing_table_s_arithmetic_rounded_to_six_places(
    pricing: RecordingPricingTable,
) -> None:
    expected = FAKE_RATE.estimate_cost(1301, 227, 4093, 8191)

    cost = estimate_worker_cost(PRICED_MODEL, FULL_USAGE)

    assert pricing.calls, "the pricing table was never consulted"
    assert cost == round(expected, 6)
    assert cost == pytest.approx(expected, abs=5e-7)


def test_a_sub_micro_dollar_spend_is_rounded_rather_than_carried_in_full(
    pricing: RecordingPricingTable,
) -> None:
    """The rounding is real: an unrounded cost differs in the seventh place."""
    usage = {"input_tokens": 1, "output_tokens": 1}
    unrounded = FAKE_RATE.estimate_cost(1, 1, 0, 0)

    cost = estimate_worker_cost(PRICED_MODEL, usage)

    assert pricing.calls, "the pricing table was never consulted"
    assert unrounded != round(unrounded, 6), "fixture no longer exercises rounding"
    assert cost == round(unrounded, 6)


def test_an_unpriced_model_costs_zero_rather_than_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``None`` from the table is an *unknown*, and a receipt cannot carry it.

    ``WorkerReceipt.usd_cost`` is a non-optional float, so returning the
    table's ``None`` would raise at the receipt boundary rather than record an
    honest zero.
    """
    table = RecordingPricingTable(None)
    monkeypatch.setattr("model_pricing.load_pricing", lambda *a, **k: table)

    cost = estimate_worker_cost("no-such-model-11718", FULL_USAGE)

    assert table.calls, "the pricing table was never consulted"
    assert table.rate is None, "the double must model a model the table cannot price"
    assert cost == 0.0
    assert isinstance(cost, float)


def test_an_unpriced_model_costs_zero_against_the_real_shipped_table() -> None:
    """The same claim without a double, so the asset itself is in the loop."""
    assert estimate_worker_cost("no-such-model-11718", FULL_USAGE) == 0.0


def test_a_zero_token_spend_is_zero(pricing: RecordingPricingTable) -> None:
    usage = dict.fromkeys(BUCKETS, 0)

    cost = estimate_worker_cost(PRICED_MODEL, usage)

    assert pricing.calls, "the pricing table was never consulted"
    assert cost == 0.0


def test_an_empty_usage_dict_is_zero_and_still_reaches_the_table(
    pricing: RecordingPricingTable,
) -> None:
    """A dict is a report of zero usage; a non-dict is no report at all."""
    cost = estimate_worker_cost(PRICED_MODEL, {})

    assert pricing.calls == [
        {
            "model": PRICED_MODEL,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 0,
            "input_includes_cache": None,
        }
    ]
    assert cost == 0.0


@pytest.mark.parametrize("bucket", BUCKETS)
def test_any_bucket_reported_as_none_reads_as_zero_rather_than_raising(
    bucket: str, pricing: RecordingPricingTable
) -> None:
    """Backends omit buckets by sending ``None``; the seam must survive it.

    Parametrized over **every** bucket rather than exercising one: a
    ``None``-tolerance written four times drifts to three the first time a
    term is edited, and the missing one raises ``TypeError`` out of a receipt
    helper — a crash in the actuator, from a field a backend is free to omit.
    """
    usage = dict(FULL_USAGE) | {bucket: None}

    cost = estimate_worker_cost(PRICED_MODEL, usage)

    assert pricing.calls, "the pricing table was never consulted"
    assert pricing.calls[0][BUCKET_TO_RATE_ARG[bucket]] == 0
    assert cost > 0.0


@pytest.mark.parametrize("bucket", BUCKETS)
def test_any_bucket_the_seam_omitted_entirely_reads_as_zero(
    bucket: str, pricing: RecordingPricingTable
) -> None:
    """The other way a bucket goes missing: the key is simply absent."""
    usage = {key: value for key, value in FULL_USAGE.items() if key != bucket}

    estimate_worker_cost(PRICED_MODEL, usage)

    assert pricing.calls, "the pricing table was never consulted"
    assert pricing.calls[0][BUCKET_TO_RATE_ARG[bucket]] == 0


def test_numeric_counts_of_another_type_are_coerced_to_int(
    pricing: RecordingPricingTable,
) -> None:
    """JSON seams hand back strings and floats; both are token counts."""
    usage = {"input_tokens": "1301", "output_tokens": 227.0}

    estimate_worker_cost(PRICED_MODEL, usage)

    assert pricing.calls[0]["input_tokens"] == 1301
    assert pricing.calls[0]["output_tokens"] == 227
    assert isinstance(pricing.calls[0]["input_tokens"], int)
    assert isinstance(pricing.calls[0]["output_tokens"], int)


def test_cached_reads_are_billed_by_the_real_shipped_pricing_table() -> None:
    """The cache-read term against the live asset, without hardcoding a price.

    A relation rather than a number: the same spend with cached reads must cost
    strictly more than without them. Dropping the term from the call makes the
    two equal.
    """
    without = dict(FULL_USAGE) | {"cache_read_input_tokens": 0}

    full_cost = estimate_worker_cost(PRICED_MODEL, FULL_USAGE)
    reduced_cost = estimate_worker_cost(PRICED_MODEL, without)

    assert full_cost > reduced_cost > 0.0


def test_cache_creation_is_billed_by_the_real_shipped_pricing_table() -> None:
    without = dict(FULL_USAGE) | {"cache_creation_input_tokens": 0}

    full_cost = estimate_worker_cost(PRICED_MODEL, FULL_USAGE)
    reduced_cost = estimate_worker_cost(PRICED_MODEL, without)

    assert full_cost > reduced_cost > 0.0


def test_the_recording_double_matches_the_real_pricing_signature() -> None:
    """Fake fidelity: the double may not assert against a shape nothing calls."""
    assert inspect.signature(RecordingPricingTable.estimate_cost) == (
        inspect.signature(ModelPricingTable.estimate_cost)
    )


# -- artifact_digest -------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["", "plan", "a" * 100_000, "line\nline\n", "  padded  "],
    ids=["empty", "word", "large", "multiline", "padded"],
)
def test_the_address_is_the_whole_sha256_of_the_utf8_bytes(text: str) -> None:
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()

    assert artifact_digest(text) == f"sha256:{expected}"


@pytest.mark.parametrize(
    "text", ["", "plan", "a" * 100_000], ids=["empty", "word", "large"]
)
def test_the_address_is_never_truncated(text: str) -> None:
    """A truncated address is a weaker one, and silently so.

    64 hex characters is the whole digest; the module previously wrote
    ``[:64]``, a bound that bounded nothing, and a hand slipping to ``[:32]``
    would have shortened every content address in the factory with no test to
    notice.
    """
    body = artifact_digest(text).removeprefix("sha256:")

    assert len(body) == 64
    assert len(artifact_digest(text)) == 71


def test_the_address_names_the_algorithm_that_produced_it() -> None:
    digest = artifact_digest("plan")

    assert digest.startswith("sha256:")
    assert digest.count(":") == 1


def test_non_ascii_output_is_addressed_by_its_utf8_bytes() -> None:
    """The encoding is load-bearing, not incidental.

    A reviewer's proposal is prose, and prose carries accents and em dashes. If
    the encoding changed, the same text would content-address differently on
    either side of the change and every stored digest would stop matching.
    """
    text = "café — naïve 🌊"
    utf8 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    latin1 = hashlib.sha256("café".encode("latin-1")).hexdigest()

    assert artifact_digest(text) == f"sha256:{utf8}"
    assert artifact_digest("café") != f"sha256:{latin1}"


def test_the_same_output_always_gets_the_same_address() -> None:
    assert artifact_digest("plan") == artifact_digest("plan")


@pytest.mark.parametrize(
    ("left", "right"),
    [("plan", "plans"), ("plan", "Plan"), ("plan", " plan"), ("", "\n")],
)
def test_different_outputs_get_different_addresses(left: str, right: str) -> None:
    assert artifact_digest(left) != artifact_digest(right)


def test_the_address_fits_the_receipt_field_that_carries_it() -> None:
    """The real bound on the digest is the receipt's, and it is enforced there.

    ``WorkerReceipt.artifact_digest`` caps at 128 characters, so this builds a
    receipt from an address for a large output rather than asserting a length
    the model might later disagree with.
    """
    receipt = refusal_receipt(
        route_policy_revision=ROUTE_REVISION,
        artifact_digest=artifact_digest("a" * 500_000),
    )

    assert receipt.artifact_digest == artifact_digest("a" * 500_000)
