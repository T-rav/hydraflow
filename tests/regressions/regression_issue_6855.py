"""Regression test for issue #6855.

Bug: ``health_monitor_loop._do_work`` iterates harness suggestions and calls
``await file_memory_suggestion(...)`` inside a bare ``except Exception: continue``
block (line 460). If the Hindsight client raises ``AuthenticationError`` or
``CreditExhaustedError`` during retain, the error is silently swallowed, then
processing continues with the next suggestion. The outer handler at line 464
also lacks a ``reraise_on_credit_or_bug`` guard.

Affected sites (both inside
``HealthMonitorLoop._run_harness_suggestion_ingestion_cycle``, which now lives
in ``src/health_monitor_loop/_heavy.py`` after the #11547 decomposition):
- the per-item ``except Exception: continue``
- the outer ``except Exception: pass`` wrapping the whole cycle

Anchored on the METHOD, not on a line number in a file: the line numbers in the
original issue rotted the moment the loop was decomposed, and a path that no
longer exists makes this test fail for the wrong reason.

Expected behaviour after fix:
  - ``AuthenticationError`` and ``CreditExhaustedError`` propagate up from
    both sites so the orchestrator's credit-pause / auth-retry logic can
    handle them.

STATUS (2026-08-23, #11664): GREEN — the guard landed. History, because it is
the whole lesson of this file:

1. The original tests anchored on LINE WINDOWS (``445 <= ln <= 475`` and
   ``abs(ln - approx_line) <= 15``). The method drifted off those windows long
   ago, so the filter matched an EMPTY set and ``assert not []`` passed
   VACUOUSLY for months while the guard was never actually present.
2. #11547 batch 4 decomposed the loop into a package, deleting the old path and
   forcing an honest re-anchor onto the enclosing METHOD. The assertion
   immediately went red on the real defect, and was parked ``xfail`` so the
   verbatim-move PR stayed behaviour-neutral. Filed as #11664.
3. This change adds ``reraise_on_credit_or_bug`` at both handlers and drops the
   markers.

Two anti-vacuity properties are now structural, and must be preserved by anyone
editing this file:

* ``_handler_anchors.method_node`` RAISES if the method name disappears, rather
  than returning an empty handler list. A rotted anchor now fails loudly
  instead of passing.
* The behavioural tests patch ``phase_utils.file_memory_suggestion`` — the
  module the code under test actually imports from. They previously patched
  ``memory.file_memory_suggestion``; there is no ``src/memory.py``, so the
  patch could never bind and the tests failed for the wrong reason, hidden
  under a non-strict ``xfail``. A behavioural test whose seam does not bind is
  the same vacuity in a different costume.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.regressions._handler_anchors import (
    _except_exception_handlers,
    method_node,
    unguarded_handlers,
)

SRC = Path(__file__).resolve().parent.parent.parent / "src"

REQUIRED_GUARD = "reraise_on_credit_or_bug"

_INGESTION_MODULE = "health_monitor_loop/_heavy.py"

#: The method that owns the OUTER handler from the issue findings.
INGESTION_SITE = (_INGESTION_MODULE, "_run_harness_suggestion_ingestion_cycle")

#: Every known site from the issue, as (module, enclosing method, description).
#:
#: The issue named two handlers in ONE method. Salvaging the un-filed tail on a
#: credit pause (fresh-eyes review on #11664) split the per-item handler out
#: into ``_file_one_harness_suggestion``, so a single anchor no longer covers
#: both. Method-scoped anchors are only rot-proof while they still enclose the
#: handlers they were written for — an extraction moves the target just as
#: surely as a line window drifts off it. Both methods are listed explicitly so
#: neither guard can be removed without a red test.
KNOWN_UNGUARDED_SITES: list[tuple[str, str, str]] = [
    (
        *INGESTION_SITE,
        "outer except Exception wrapping harness suggestion ingestion",
    ),
    (
        _INGESTION_MODULE,
        "_file_one_harness_suggestion",
        "per-item except Exception around file_memory_suggestion",
    ),
]


class TestSiteAnchorsStillResolve:
    """The anti-vacuity tripwire, deliberately UNMARKED.

    Landed by #11665 while the checks below were still ``xfail``: ``xfail``
    swallows EVERY exception in a marked test body, including the
    ``AssertionError`` ``method_node`` raises when an anchor is gone. The guard
    written to stop this file passing vacuously would itself have been unable to
    turn the suite red — the same failure mode, one layer up.

    The markers are gone now that the fix has landed, but this stays: it is the
    check that fails when an anchor stops pointing at real code, independent of
    whatever the assertions below happen to conclude. It earned its keep during
    #11664 — extracting ``_file_one_harness_suggestion`` moved a handler out of
    the anchored method, exactly the drift
    ``test_the_anchor_still_encloses_broad_handlers`` exists to catch.
    """

    @pytest.mark.parametrize(
        ("filename", "method"),
        [(f, m) for f, m, _ in KNOWN_UNGUARDED_SITES],
        ids=[f"{f}:{m}" for f, m, _ in KNOWN_UNGUARDED_SITES],
    )
    def test_site_module_and_method_exist(self, filename: str, method: str) -> None:
        filepath = SRC / filename
        assert filepath.exists(), (
            f"{filename} does not exist — the #6855 checks below are anchored "
            "at a path that moved, and would report nothing. Re-point them."
        )
        # Raises a descriptive AssertionError if the method is gone.
        assert method_node(filepath, method) is not None

    @pytest.mark.parametrize(
        ("filename", "method"),
        [(f, m) for f, m, _ in KNOWN_UNGUARDED_SITES],
        ids=[f"{f}:{m}" for f, m, _ in KNOWN_UNGUARDED_SITES],
    )
    def test_the_anchor_still_encloses_broad_handlers(
        self, filename: str, method: str
    ) -> None:
        """Each anchored method must still CONTAIN a broad handler.

        Existing is not enough: if an ``except Exception`` block is refactored
        out of its anchored method, the guard checks below find zero handlers
        and read as "guarded" when nothing was verified.
        """
        handlers = _except_exception_handlers(method_node(SRC / filename, method))
        assert handlers, (
            f"{method}() no longer contains any ``except Exception`` block. "
            "Either the handler moved (re-point the anchor, or add the new "
            "enclosing method to KNOWN_UNGUARDED_SITES) or this entry is stale "
            "— either way the guard checks below are now vacuous for it."
        )


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------
#
# Shared with the sibling guard regressions (#6752, #6766, #6809, #6814, #6983)
# via ``_handler_anchors``. ``method_node`` RAISES when the method is gone
# rather than returning an empty result — that raise is what stops this test
# from ever rotting back into the vacuous pass described above. See that
# module's docstring for the full statement of the line-anchor rot class.


# ---------------------------------------------------------------------------
# AST-based: verify source has the guard
# ---------------------------------------------------------------------------


class TestHealthMonitorSuggestionIngestionBlocksHaveReraise:
    """AST check — the ``except Exception`` blocks surrounding harness
    suggestion ingestion in health_monitor_loop.py must call
    ``reraise_on_credit_or_bug``.
    """

    def test_suggestion_ingestion_except_blocks_have_reraise_guard(self) -> None:
        module, method = INGESTION_SITE
        filepath = SRC / module
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = unguarded_handlers(filepath, method)

        assert not unguarded, (
            f"{module} has unguarded ``except Exception`` block(s) in "
            f"{method}().\nLines: {[ln for ln, _ in unguarded]}\n"
            f"Auth/credit failures are silently swallowed — see issue #6855."
        )


class TestKnownSitesHaveReraiseGuard:
    """Parametrised check for each specific site from the issue findings."""

    @pytest.mark.parametrize(
        ("filename", "method", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{m}" for f, m, _ in KNOWN_UNGUARDED_SITES],
    )
    def test_known_site_has_reraise_guard(
        self, filename: str, method: str, desc: str
    ) -> None:
        filepath = SRC / filename
        assert filepath.exists()

        nearby = [ln for ln, _ in unguarded_handlers(filepath, method)]

        assert not nearby, (
            f"{filename}:{method}() ({desc}) — ``except Exception`` "
            f"at line {nearby[0]} does not call reraise_on_credit_or_bug(). "
            f"Auth/credit failures are silently swallowed (issue #6855)."
        )


# ---------------------------------------------------------------------------
# Behavioural: AuthenticationError / CreditExhaustedError must propagate
# ---------------------------------------------------------------------------


class TestHealthMonitorSuggestionIngestionPropagatesFatalErrors:
    """Behavioural tests — when ``file_memory_suggestion`` raises
    ``AuthenticationError`` or ``CreditExhaustedError``, the exception
    must NOT be swallowed by the per-item or outer except blocks.

    Driven through ``_run_harness_suggestion_ingestion_cycle`` directly rather
    than ``_do_work``: the cycle is only reached on the heavy-pass cadence, so
    going through ``_do_work`` makes the test pass whenever the gate happens to
    be shut — a green that proves nothing.
    """

    @pytest.fixture()
    def loop_with_suggestion(self, tmp_path: Path) -> object:
        """A HealthMonitorLoop with exactly one pending harness suggestion."""
        loop = _make_health_monitor(tmp_path)
        memory_dir = loop._config.repo_memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "harness_suggestions.jsonl").write_text(
            '{"suggestion":"test principle","title":"test","occurrences":1,'
            '"category":"test_cat"}\n',
            encoding="utf-8",
        )
        return loop

    @pytest.mark.asyncio()
    @pytest.mark.parametrize(
        "fatal_name", ["AuthenticationError", "CreditExhaustedError"]
    )
    async def test_fatal_error_propagates(
        self,
        loop_with_suggestion: object,
        monkeypatch: pytest.MonkeyPatch,
        fatal_name: str,
    ) -> None:
        """A credit/auth failure escapes the cycle so the orchestrator can pause."""
        import subprocess_util

        fatal_cls = getattr(subprocess_util, fatal_name)
        _patch_file_memory_suggestion(monkeypatch, fatal_cls("fatal"))

        with pytest.raises(fatal_cls):
            await loop_with_suggestion._run_harness_suggestion_ingestion_cycle()

    @pytest.mark.asyncio()
    async def test_ordinary_error_is_still_swallowed(
        self, loop_with_suggestion: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative control: the guard is narrow, not a blanket re-raise.

        Without this, a handler that simply re-raised everything would satisfy
        the two tests above while breaking the loop's tolerance for one
        malformed suggestion — which is the behaviour the broad handler exists
        to provide.
        """
        # ConnectionError is neither infra-fatal nor a likely-bug type, so
        # `reraise_on_credit_or_bug` must let the handler absorb it.
        _patch_file_memory_suggestion(monkeypatch, ConnectionError("transient"))

        await loop_with_suggestion._run_harness_suggestion_ingestion_cycle()


class TestCreditPauseDoesNotDuplicateAlreadyFiledSuggestions:
    """Letting the error out must not turn into re-filing on resume.

    ``file_memory_suggestion`` mints a fresh uuid per call and never dedups, so
    if the cycle aborts mid-batch and leaves the whole JSONL in place, the next
    heavy pass re-files every suggestion that already landed. Found by the
    fresh-eyes review on #11664: the guard fixed the swallow but introduced
    duplicate work on the resume path.
    """

    @pytest.mark.asyncio()
    async def test_only_the_unfiled_tail_survives_a_credit_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock

        from subprocess_util import CreditExhaustedError

        loop = _make_health_monitor(tmp_path)
        memory_dir = loop._config.repo_memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / "harness_suggestions.jsonl"
        path.write_text(
            "".join(
                f'{{"suggestion":"s{n}","title":"t{n}","occurrences":1,'
                f'"category":"c"}}\n'
                for n in range(4)
            ),
            encoding="utf-8",
        )

        # First two file fine; the third hits an exhausted account.
        import phase_utils

        monkeypatch.setattr(
            phase_utils,
            "file_memory_suggestion",
            AsyncMock(side_effect=[None, None, CreditExhaustedError("dry"), None]),
            raising=True,
        )

        with pytest.raises(CreditExhaustedError):
            await loop._run_harness_suggestion_ingestion_cycle()

        remaining = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]
        assert [json.loads(ln)["suggestion"] for ln in remaining] == ["s2", "s3"], (
            "the two suggestions already filed must be dropped and only the "
            "un-filed tail kept — otherwise the next heavy pass re-files s0/s1 "
            "as fresh memory items with new uuids"
        )

    @pytest.mark.asyncio()
    async def test_file_is_emptied_when_the_whole_batch_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Happy path unchanged: a clean pass still consumes the whole file."""
        from unittest.mock import AsyncMock

        loop = _make_health_monitor(tmp_path)
        memory_dir = loop._config.repo_memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / "harness_suggestions.jsonl"
        path.write_text(
            '{"suggestion":"s0","title":"t0","occurrences":1,"category":"c"}\n',
            encoding="utf-8",
        )

        import phase_utils

        monkeypatch.setattr(
            phase_utils, "file_memory_suggestion", AsyncMock(), raising=True
        )

        await loop._run_harness_suggestion_ingestion_cycle()

        assert path.read_text(encoding="utf-8").strip() == ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_file_memory_suggestion(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    """Make ``file_memory_suggestion`` raise *error*.

    Patches ``phase_utils`` — the module the code under test imports from
    (a deferred, in-method ``from phase_utils import file_memory_suggestion``,
    so the lookup happens at call time and this binds). ``raising=True`` is
    deliberate: if the symbol ever moves, this errors loudly instead of
    silently patching nothing and leaving the test to pass for free.
    """
    from unittest.mock import AsyncMock

    import phase_utils

    monkeypatch.setattr(
        phase_utils,
        "file_memory_suggestion",
        AsyncMock(side_effect=error),
        raising=True,
    )


def _make_health_monitor(data_dir: Path) -> object:
    """Build a HealthMonitorLoop with data_root pointing at *data_dir*.

    Uses ``make_bg_loop_deps`` to get a real LoopDeps, then overrides
    ``data_root`` so ``data_path("memory", ...)`` resolves to the tmp dir.
    """
    from health_monitor_loop import HealthMonitorLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(data_dir)
    config = bg.config
    # Bypass Pydantic __setattr__ to point data_root at our fixture dir
    object.__setattr__(config, "data_root", data_dir)

    return HealthMonitorLoop(config=config, deps=bg.loop_deps)
