"""Cross-cutting exception classification utilities.

This module lives at the Infrastructure/Cross-cutting boundary so that
both Application-layer code (``phase_utils``) and Infrastructure-layer
code (``merge_conflict_resolver``) can import it without creating upward
dependency violations.

Extracted from ``phase_utils`` as part of the architecture layering fix
(issue #5919).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from subprocess_util import AuthenticationError, CreditExhaustedError

if TYPE_CHECKING:
    from ports import ObservabilityPort

logger = logging.getLogger("exception_classify")

#: Exception types that almost certainly indicate a code bug rather than a
#: transient/environmental failure.  When one of these is caught in a
#: catch-all handler, it should be logged at a higher severity so operators
#: can distinguish "needs a code fix" from "will probably succeed on retry".
LIKELY_BUG_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TypeError,
    KeyError,
    AttributeError,
    ValueError,
    IndexError,
    NotImplementedError,
)


#: Infrastructure failures that make further work pointless: the harness has
#: no usable credential, no remaining billing budget, or no memory headroom.
#: None of the three is retryable, so a handler that would otherwise absorb an
#: exception must let these through.  Use this in an ``except`` clause that
#: re-raises ahead of a handler which already classifies the rest.
INFRA_FATAL_EXCEPTIONS: tuple[type[BaseException], ...] = (
    AuthenticationError,
    CreditExhaustedError,
    MemoryError,
)

#: The canonical "must never be swallowed" set — the infrastructure failures
#: above plus the likely-bug class.  This is the ONE definition of fatal;
#: re-stating it as a literal tuple at a call site is how the concurrent
#: worker pools drifted from it and quietly dropped ``TypeError`` (#11618).
FATAL_EXCEPTIONS: tuple[type[BaseException], ...] = (
    *INFRA_FATAL_EXCEPTIONS,
    *LIKELY_BUG_EXCEPTIONS,
)


def is_likely_bug(exc: BaseException) -> bool:
    """Return True if *exc* is likely a code bug rather than a transient failure."""
    return isinstance(exc, LIKELY_BUG_EXCEPTIONS)


def is_fatal(exc: BaseException) -> bool:
    """Return True if *exc* must not be swallowed by a catch-all handler.

    The predicate behind :func:`reraise_on_credit_or_bug`, exposed separately
    for handlers that need to *do* something before re-raising — a worker pool
    cancelling its sibling tasks, say.  Both must agree on what fatal means:
    the divergence between them is exactly what #11618 fixed.
    """
    return isinstance(exc, FATAL_EXCEPTIONS)


def exc_detail(exc: BaseException) -> str:
    """Return a non-empty, human-readable detail string for *exc*.

    Many exceptions carry an empty ``str()`` — e.g. a subprocess error raised
    with empty stderr, or a bare ``RuntimeError()`` — which produces useless
    log lines like ``"Review failed for PR #8672: "`` (nothing after the
    colon). This helper guarantees a diagnostic remains by falling back to
    ``repr(exc)`` and finally the exception's type name.

    Use it anywhere ``str(exc)`` is interpolated into a log message without
    ``exc_info=True`` to back-stop the empty-message case.
    """
    return str(exc).strip() or repr(exc).strip() or type(exc).__name__


def capture_if_bug(
    exc: Exception,
    obs: ObservabilityPort | None = None,
    **context: object,
) -> None:
    """Send to the observability port only if the exception looks like a real bug.

    When *obs* is ``None`` there is no backend to route to, so the call is a
    no-op. Call sites that want capture should thread an injected
    ``ObservabilityPort`` (backed by the no-op adapter until the SRE agent
    wires a real one, ADR-0118).
    """
    if obs is None:
        return
    if is_likely_bug(exc):
        obs.capture_exception(exc)
    else:
        obs.breadcrumb(
            "transient_error",
            str(exc)[:500],
            level="warning",
            **context,
        )


def reraise_on_credit_or_bug(exc: BaseException) -> None:
    """Re-raise *exc* if it is a fatal infrastructure error or a likely bug.

    Call this at the top of an ``except Exception`` handler to replace the
    duplicated pattern::

        except (AuthenticationError, CreditExhaustedError):
            raise
        except Exception as exc:
            if is_likely_bug(exc):
                raise

    with the shorter::

        except Exception as exc:
            reraise_on_credit_or_bug(exc)

    "Fatal" is :data:`FATAL_EXCEPTIONS` — see :func:`is_fatal`.
    """
    if is_fatal(exc):
        raise exc
