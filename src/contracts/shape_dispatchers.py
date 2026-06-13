"""Shape-validating dispatchers for LiveCorpusReplayLoop (Phase 5 of #8786).

The first dispatcher to populate ``LiveCorpusReplayLoop``'s registry. Rather
than mirror every gh call shape through a per-method ``FakeGitHub`` invocation
(needs careful state seeding to be meaningful), this dispatcher validates the
sampled stdout against the matching Pydantic shape from
``contracts.shapes``. A validation failure IS the drift signal — gh changed a
field, removed one, or returned a new enum value.

Why this is useful before per-method dispatchers exist:

- Shape drift is the *highest-frequency* drift in practice. New gh versions
  add fields; removed fields break downstream parsers. Catching that at
  shadow-corpus replay time means we hear about it within one tick
  (~15 min), not when a production loop crashes parsing the new shape.
- Zero state-seeding required. The dispatcher is purely defensive against
  upstream changes, not a fake-correctness check.
- Adding per-method value-comparison dispatchers later doesn't conflict —
  they'd register under different ``(adapter, command)`` keys or the same
  key with a richer body that still validates first.

The dispatcher returns ``None`` when validation succeeds (sample matches the
shape — no drift). On validation failure it returns a dict that surfaces the
expected shape vs the sampled payload, which the loop diffs to produce the
drift signature. The signature is stable across reruns of the same drift.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from contracts.shadow_classifier import SHAPE_VERDICT_KEY
from contracts.shapes import (
    GhCheckRun,
    GhIssueListItem,
    GhIssueSummary,
    GhPRDetail,
    GhPRSummary,
)

if TYPE_CHECKING:
    from contracts.shadow import ShadowSample

logger = logging.getLogger("hydraflow.contracts.shape_dispatchers")

# Map ``(command0_after_gh, shape_keyword)`` → Pydantic model.
# Detection is heuristic on args — the dispatcher inspects ``--json
# FIELDS`` for tell-tale fields and chooses the most-specific shape.
# Unrecognized shapes return None (no opinion = loop skips).


def _pick_shape_for_pr(args: list[str]) -> type[BaseModel] | None:
    """``gh pr ...`` shape selection. Detect summary vs detail by which
    detail-only fields are requested in ``--json FIELDS``.

    Only select a shape when ALL of its required fields are present in the
    requested field set.  Narrow projection calls (e.g. ``--json commits``,
    ``--json reviews``, ``--json headRefOid``) don't include all required
    fields, so the dispatcher returns ``None`` to avoid false-positive drift
    signals for those projection-only shadow-corpus samples.
    """
    fields = _extract_json_fields(args)
    if fields is None:
        return None
    detail_signals = {
        "headRefName",
        "baseRefName",
        "headRefOid",
        "mergeable",
        "isDraft",
    }
    if fields & detail_signals:
        # GhPRDetail requires number — skip projection-only calls like --json headRefOid
        if "number" not in fields:
            return None
        return GhPRDetail
    # GhPRSummary requires number, title, state
    if not {"number", "title", "state"} <= fields:
        return None
    return GhPRSummary


def _pick_shape_for_issue(args: list[str]) -> type[BaseModel] | None:
    """Issue shape selection based on which fields are requested.

    ``GhIssueSummary`` requires ``number`` and ``state`` — only use it when
    the call requests both.  Narrow calls like ``--json state,stateReason``
    (which omit ``number``) would otherwise fail validation on the required
    ``number`` field, producing a false-positive drift signal.  Calls that
    request fields outside both shapes (e.g. ``--json comments``) get
    ``None`` so the dispatcher skips them.
    """
    fields = _extract_json_fields(args)
    if fields is None:
        return None
    if "state" in fields:
        # GhIssueSummary requires both number and state
        if "number" not in fields:
            return None
        return GhIssueSummary
    if "number" in fields and "title" in fields:
        return GhIssueListItem
    return None


def _pick_shape_for_issue_list(args: list[str]) -> type[BaseModel] | None:
    fields = _extract_json_fields(args)
    if fields is None:
        return None
    return GhIssueListItem


def _pick_shape_for_checks(args: list[str]) -> type[BaseModel] | None:
    fields = _extract_json_fields(args)
    if fields is None:
        return None
    return GhCheckRun


def _extract_json_fields(args: list[str]) -> frozenset[str] | None:
    """Return the set of fields requested via ``--json A,B,C``.

    Returns None when no ``--json`` flag is present — the call isn't
    asking for a JSON payload, so shape validation is meaningless.
    """
    try:
        idx = args.index("--json")
    except ValueError:
        return None
    if idx + 1 >= len(args):
        return None
    return frozenset(args[idx + 1].split(","))


def _gh_subcommand(args: list[str]) -> str | None:
    """Return the gh subcommand pair, e.g. ``"pr-view"``, or None."""
    if len(args) < 2:
        return None
    return f"{args[0]}-{args[1]}"


# Minimum fields a call must request before we'll validate against a shape.
# Narrow queries (e.g. ``--json commits``, ``--json headRefOid``) omit
# required fields, so validating against a shape that needs them produces
# spurious drift signals.
_SHAPE_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "GhPRSummary": frozenset({"number", "title", "state"}),
    "GhPRDetail": frozenset({"number"}),
    "GhIssueSummary": frozenset({"number", "state"}),
    "GhIssueListItem": frozenset({"number", "title"}),
    "GhCheckRun": frozenset({"name"}),
}


async def gh_shape_validator(sample: ShadowSample) -> dict[str, object] | None:  # noqa: PLR0911
    """Dispatcher: validate ``sample.stdout`` against the matching shape.

    Returns:
        - ``None`` if the sample's stdout validates cleanly — no drift.
        - A diff-payload dict if validation fails — the loop fingerprints
          this to file a single drift issue per signature.
        - ``None`` for samples this dispatcher has no opinion on
          (unknown subcommand, no ``--json`` flag, ``--jq`` transform
          applied, empty stdout, requested fields don't cover the shape's
          required fields, etc.) — the loop treats those as
          "skipped, no opinion".
    """
    if sample.adapter != "github" or sample.command != "gh":
        return None
    if not sample.stdout.strip():
        return None
    # --jq transforms output to an arbitrary shape (scalar, array, etc.);
    # shape validation against a fixed Pydantic model is meaningless.
    if "--jq" in sample.args:
        return None
    subcommand = _gh_subcommand(sample.args)
    if subcommand is None:
        return None

    shape_cls: type[BaseModel] | None = None
    if subcommand in ("pr-view", "pr-list"):
        shape_cls = _pick_shape_for_pr(sample.args)
    elif subcommand == "issue-view":
        shape_cls = _pick_shape_for_issue(sample.args)
    elif subcommand == "issue-list":
        shape_cls = _pick_shape_for_issue_list(sample.args)
    elif subcommand == "pr-checks":
        shape_cls = _pick_shape_for_checks(sample.args)
    if shape_cls is None:
        return None

    # Only validate when the requested fields cover the shape's required
    # fields.  Narrow queries (e.g. ``--json commits``, ``--json headRefOid``)
    # don't request the required fields, so attempting to validate them
    # produces false-positive drift for every valid call of that shape.
    requested = _extract_json_fields(sample.args)
    required = _SHAPE_REQUIRED_FIELDS.get(shape_cls.__name__, frozenset())
    if requested is not None and not required.issubset(requested):
        return None

    try:
        parsed_payload = json.loads(sample.stdout)
    except json.JSONDecodeError as exc:
        logger.debug("gh_shape_validator: stdout for %s not JSON: %s", subcommand, exc)
        return None

    # gh --json sometimes returns a single object, sometimes a list of
    # them. Validate each element when it's a list.
    candidates = (
        parsed_payload if isinstance(parsed_payload, list) else [parsed_payload]
    )
    failures: list[dict[str, object]] = []
    for i, item in enumerate(candidates):
        try:
            shape_cls.model_validate(item)
        except ValidationError as exc:
            failures.append(
                {
                    "index": i,
                    "shape": shape_cls.__name__,
                    "errors": _summarize_errors(exc),
                }
            )
    if not failures:
        return None
    return {
        SHAPE_VERDICT_KEY: True,
        "shape": shape_cls.__name__,
        "subcommand": subcommand,
        "failure_count": len(failures),
        "failures": failures[:5],  # cap body length
    }


def _summarize_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Compact error report — one entry per offending field/value."""
    out: list[dict[str, str]] = []
    for err in exc.errors()[:10]:
        out.append(
            {
                "loc": ".".join(str(p) for p in err.get("loc", ())),
                "type": str(err.get("type", "")),
                "msg": str(err.get("msg", ""))[:200],
            }
        )
    return out
