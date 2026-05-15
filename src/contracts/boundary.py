"""I/O-boundary validation helper for adapter call sites (Phase 7 of #8786).

The Pydantic shapes in ``contracts.shapes`` catch drift at the call site —
but only if call sites actually validate. This module provides the small,
non-intrusive helper that lets ``PRManager``, ``FakeGitHub``, and friends
opt in without changing their return type or breaking on novel inputs.

Contract:

- ``parse_with_shape(json_str, model)`` returns a typed
  :class:`BoundaryParseResult`. ``payload`` is always populated when the
  JSON parsed at all; ``model_instance`` is the validated Pydantic model
  when validation succeeded, else None; ``validation_error`` carries a
  compact diagnostic on failure.
- The helper NEVER raises on validation failure — it logs at WARNING and
  returns a partial result. Call sites that want strict behaviour check
  ``model_instance is None`` and raise themselves.
- JSON parse failures (truly malformed input) DO raise ``ValueError`` so
  callers don't silently fall back to a stale value.

Why this shape:

- Existing call sites do ``json.loads(stdout)`` → dict and access fields
  by key. Migrating them to a typed model is a big refactor. This
  helper lets them log shape drift today without touching their hot
  path; tightening to ``raise`` on validation failure is a per-call-site
  decision once the corpus is stable enough.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("hydraflow.contracts.boundary")

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class BoundaryValidationError:
    """Compact, log-friendly diagnostic for a single failed validation."""

    shape: str
    failure_count: int
    sample: list[dict[str, str]]  # up to N errors, one per offending field


@dataclass(frozen=True)
class BoundaryParseResult:
    """Outcome of a call-site validation."""

    payload: object | None
    model_instance: BaseModel | None
    validation_error: BoundaryValidationError | None

    @property
    def ok(self) -> bool:
        """True iff JSON parsed AND the shape validated."""
        return self.model_instance is not None and self.validation_error is None


def parse_with_shape(json_str: str, model: type[T]) -> BoundaryParseResult:
    """Parse *json_str* and validate it against *model*.

    Returns a BoundaryParseResult capturing all three possible outcomes:
    parse OK + validation OK, parse OK + validation fail, parse fail
    (raises ValueError so the caller can't silently fall back).
    """
    try:
        payload = json.loads(json_str)
    except json.JSONDecodeError as exc:
        msg = f"could not parse JSON at boundary: {exc}"
        raise ValueError(msg) from exc

    try:
        instance = model.model_validate(payload)
    except ValidationError as exc:
        diag = BoundaryValidationError(
            shape=model.__name__,
            failure_count=len(exc.errors()),
            sample=[
                {
                    "loc": ".".join(str(p) for p in e.get("loc", ())),
                    "type": str(e.get("type", "")),
                    "msg": str(e.get("msg", ""))[:200],
                }
                for e in exc.errors()[:10]
            ],
        )
        logger.warning(
            "boundary validation failed for %s (count=%d): %s",
            model.__name__,
            diag.failure_count,
            diag.sample[0] if diag.sample else "no detail",
        )
        return BoundaryParseResult(
            payload=payload, model_instance=None, validation_error=diag
        )

    return BoundaryParseResult(
        payload=payload, model_instance=instance, validation_error=None
    )


def parse_list_with_shape(json_str: str, model: type[T]) -> list[BoundaryParseResult]:
    """Parse *json_str* as a list and validate each element against *model*.

    Returns one BoundaryParseResult per list element. Element-level
    failures don't poison sibling elements — each carries its own
    validation outcome.
    """
    try:
        payload = json.loads(json_str)
    except json.JSONDecodeError as exc:
        msg = f"could not parse JSON list at boundary: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(payload, list):
        msg = (
            f"expected JSON list at boundary, got {type(payload).__name__}: {payload!r}"
        )
        raise ValueError(msg)

    out: list[BoundaryParseResult] = []
    for i, item in enumerate(payload):
        try:
            instance = model.model_validate(item)
        except ValidationError as exc:
            diag = BoundaryValidationError(
                shape=model.__name__,
                failure_count=len(exc.errors()),
                sample=[
                    {
                        "loc": ".".join(str(p) for p in e.get("loc", ())),
                        "type": str(e.get("type", "")),
                        "msg": str(e.get("msg", ""))[:200],
                    }
                    for e in exc.errors()[:10]
                ],
            )
            logger.warning(
                "boundary validation failed for %s[%d]: %s",
                model.__name__,
                i,
                diag.sample[0] if diag.sample else "no detail",
            )
            out.append(
                BoundaryParseResult(
                    payload=item, model_instance=None, validation_error=diag
                )
            )
        else:
            out.append(
                BoundaryParseResult(
                    payload=item, model_instance=instance, validation_error=None
                )
            )
    return out
