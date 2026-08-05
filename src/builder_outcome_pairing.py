"""Builder → outcome pairing (#11027) — the prompt-of-record join.

The missing link ADR-0130 named: the ADR-0087 rubric scores a prompt *builder by
name*, but every outcome series (verdict pass rate, retries, escapes, cost) is
keyed by ``issue_number``, and nothing tied a builder to the outcomes of the work
it produced. Mechanism B of the #11027 ruling closes it **without threading a
builder name through every runner**: the prompt observatory already records a
per-prompt *shape* at the gate (now tagged with ``issue_number``, #11027) and
already knows how to bridge a shape to a registered builder by token resemblance.

This pure engine does the join:

    observed shape  --(resemblance ≥ threshold, UNAMBIGUOUS)-->  builder
    observed shape  --(issue_number tag)-->                      issue
    issue           --(caller-supplied)-->                       outcome

and only attributes a shape to a builder when **exactly one** registered builder
resembles it above the threshold — otherwise it abstains (an ambiguous or
unrecognized shape yields no attribution, never a confident-but-wrong one). The
result is an ``OutcomeSnapshot`` per builder that feeds
``prompt_outcome_pairing.pairing_verdict``; ``prompt_fitness.outcome_paired`` may
flip ``True`` only for builders this join attributes unambiguously.

No I/O: the caller loads the observed-shape rows and the per-issue outcomes (from
the ConvergenceLedger / escape ledger / inferences.jsonl) and passes them in.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from prompt_observatory import (
    RESEMBLANCE_THRESHOLD,
    registry_token_sets,
    resemblance,
)
from prompt_outcome_pairing import OutcomeSnapshot


def resolve_builder(
    tokens: frozenset[str],
    registry: Mapping[str, frozenset[str]],
    *,
    threshold: float = RESEMBLANCE_THRESHOLD,
) -> str | None:
    """The single registered builder whose fixture resembles ``tokens``, or None.

    Abstains (returns None) when zero builders clear the threshold OR when more
    than one does — an ambiguous shape must never be attributed to a guessed
    builder. This is the whole point of the honest-``False`` contract in #10855.
    """
    matches = [
        name
        for name, reg_tokens in registry.items()
        if resemblance(tokens, reg_tokens) >= threshold
    ]
    return matches[0] if len(matches) == 1 else None


def builder_issue_links(
    records: Iterable[Mapping[str, object]],
    *,
    registry: Mapping[str, frozenset[str]] | None = None,
    threshold: float = RESEMBLANCE_THRESHOLD,
) -> dict[str, set[int]]:
    """Map each builder to the set of issues whose gated prompts it produced.

    Reads observed-shape rows (``observatory`` JSONL, each carrying ``tokens``
    and — since #11027 — ``issue_number``). A row without a token list (too thin
    to identify) or without an issue tag is skipped, as is one whose shape does
    not resolve to a single builder.
    """
    reg = dict(registry) if registry is not None else registry_token_sets()
    links: dict[str, set[int]] = defaultdict(set)
    for record in records:
        issue = record.get("issue_number")
        raw_tokens = record.get("tokens")
        # isinstance narrows `issue` to int (no cast/suppression needed) and
        # skips a thin row whose shape is too sparse to carry a token list.
        if not isinstance(issue, int) or not isinstance(
            raw_tokens, (list, tuple, frozenset, set)
        ):
            continue
        builder = resolve_builder(frozenset(raw_tokens), reg, threshold=threshold)
        if builder is not None:
            links[builder].add(issue)
    return dict(links)


@dataclass(frozen=True)
class IssueOutcome:
    """One issue's paired outcome, as the caller resolves it from the ledgers.

    ``passed`` = the work converged / the gate advanced; ``retries`` = loop-backs
    on that issue; ``escaped`` = a merge from this issue was later escape-attributed
    (#10367); ``cost`` = USD spent on it.
    """

    passed: bool
    retries: int
    escaped: bool
    cost: float


def builder_outcome_snapshot(
    issues: set[int],
    outcomes: Mapping[int, IssueOutcome],
    *,
    model_version: str = "",
) -> OutcomeSnapshot | None:
    """Aggregate a builder's issues into one ``OutcomeSnapshot``, or None.

    Only issues present in ``outcomes`` count (an unresolved issue is dropped, not
    assumed good). Returns None when the builder has no resolved issues — no
    snapshot rather than a zero-sample one. ``cost_per_success`` is total cost
    over the successful issues (or total cost when none succeeded, so a
    zero-success builder still reports a finite, honest efficiency number).
    """
    resolved = [outcomes[i] for i in issues if i in outcomes]
    n = len(resolved)
    if n == 0:
        return None
    successes = [o for o in resolved if o.passed]
    total_cost = sum(o.cost for o in resolved)
    denom_cost = len(successes) or n
    return OutcomeSnapshot(
        pass_rate=len(successes) / n,
        retry_rate=sum(o.retries for o in resolved) / n,
        escape_rate=sum(1 for o in resolved if o.escaped) / n,
        cost_per_success=total_cost / denom_cost,
        n_samples=n,
        model_version=model_version,
    )


def pair_builders(
    links: Mapping[str, set[int]],
    outcomes: Mapping[int, IssueOutcome],
    *,
    model_version: str = "",
) -> dict[str, OutcomeSnapshot]:
    """Builder -> its aggregated outcome snapshot, skipping builders with none."""
    paired: dict[str, OutcomeSnapshot] = {}
    for builder, issues in links.items():
        snapshot = builder_outcome_snapshot(
            issues, outcomes, model_version=model_version
        )
        if snapshot is not None:
            paired[builder] = snapshot
    return paired
