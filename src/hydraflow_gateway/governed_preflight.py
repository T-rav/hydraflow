"""Strict pre-upstream request binding for a governed key (ADR-0141 D3).

A route-bound virtual key names exactly one effective model. This module is the
predicate the proxy asks *before* it constructs an upstream request object, so a
request that disagrees with its binding sends zero upstream bytes as a matter of
control flow rather than of observation.

Three deliberate properties:

* **The supported face set is an allow-list.** A governed key reaches an
  enumerated Anthropic message face or nothing. Merely observing a model after
  bytes reached upstream is not enforcement, and a face this module cannot parse
  is a face it cannot bind — so it refuses rather than waving it through.
* **A duplicate key anywhere in the body is a refusal.** ``json.loads`` resolves
  duplicates last-write-wins, which means two parsers can legitimately disagree
  about what the body says. A body whose meaning depends on the parser is not a
  body a binding can be checked against.
* **A refusal never quotes the body.** These exceptions reach the gateway's
  logs, and a governed request body is a prompt.
"""

from __future__ import annotations

import json
from enum import StrEnum

GOVERNED_MESSAGE_PATHS: frozenset[str] = frozenset(
    {
        "/v1/messages",
        # Carries its own ``model`` key and is the CLI's context accounting call,
        # so it is bound exactly like the message face rather than exempted.
        "/v1/messages/count_tokens",
    }
)
"""The only request faces a route-bound key may reach.

Widening this set is the compatibility-probe follow-up the design names: every
additional Claude CLI face has to be shown to carry a model binding as strong as
this one before it is added, and until then it is refused.
"""

_JSON_CONTENT_TYPE = "application/json"
_MODEL_KEY = "model"
_JSON_ERRORS = (UnicodeDecodeError, ValueError, RecursionError)


class PreflightRefusal(StrEnum):
    """Why a governed request was refused before any upstream byte."""

    UNBOUND_GOVERNED_KEY = "unbound-governed-key"
    UNSUPPORTED_REQUEST_FACE = "unsupported-request-face"
    UNSUPPORTED_CONTENT_TYPE = "unsupported-content-type"
    BODY_NOT_JSON_OBJECT = "body-not-json-object"
    DUPLICATE_MODEL_KEY = "duplicate-model-key"
    MISSING_MODEL_KEY = "missing-model-key"
    MODEL_NOT_BOUND = "model-not-bound"


class GovernedRequestRefused(Exception):
    """A governed request did not satisfy its key's immutable binding."""

    def __init__(self, refusal: PreflightRefusal) -> None:
        # The code is the whole message: a refusal can be logged, and the body
        # that caused it is a prompt.
        super().__init__(refusal.value)
        self.refusal = refusal


def governed_path_supported(path: str) -> bool:
    """Whether a route-bound key may reach *path* at all."""
    return path.rstrip("/") in GOVERNED_MESSAGE_PATHS or path in GOVERNED_MESSAGE_PATHS


class _DuplicateKey(ValueError):
    """A JSON object declared the same key twice."""


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def check_governed_body(body: bytes, *, bound_model: str, content_type: str) -> None:
    """Raise :class:`GovernedRequestRefused` unless *body* names *bound_model*.

    The comparison is whitespace- and case-insensitive because the bound model
    travels through an argv and a JSON body that are written by different code,
    and neither difference is a binding violation. Everything else is.
    """
    media_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if media_type != _JSON_CONTENT_TYPE:
        raise GovernedRequestRefused(PreflightRefusal.UNSUPPORTED_CONTENT_TYPE)
    try:
        payload = json.loads(body, object_pairs_hook=_reject_duplicates)
    except _DuplicateKey as exc:
        raise GovernedRequestRefused(PreflightRefusal.DUPLICATE_MODEL_KEY) from exc
    except _JSON_ERRORS as exc:
        raise GovernedRequestRefused(PreflightRefusal.BODY_NOT_JSON_OBJECT) from exc
    if not isinstance(payload, dict):
        raise GovernedRequestRefused(PreflightRefusal.BODY_NOT_JSON_OBJECT)
    model = payload.get(_MODEL_KEY)
    if not isinstance(model, str) or not model.strip():
        raise GovernedRequestRefused(PreflightRefusal.MISSING_MODEL_KEY)
    if model.strip().lower() != bound_model.strip().lower():
        raise GovernedRequestRefused(PreflightRefusal.MODEL_NOT_BOUND)
