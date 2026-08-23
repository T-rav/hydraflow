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

These tests assert the *correct* behaviour and are RED against the current
(buggy) code.

STATUS (2026-08-23, #11547 batch 4): still RED. The #6855 guard was never
added at either site. The line-window anchors above (``445 <= ln <= 475`` /
``abs(ln - approx_line) <= 15``) had drifted off the method years ago, so both
tests were matching an empty window and passing VACUOUSLY. Re-anchoring them on
the enclosing METHOD — which the god-class decomposition forced, since the old
path no longer exists — restored the real assertion and it fails, correctly.
Marked ``xfail`` (the ``regression_issue_6630.py`` convention) rather than
fixed: the decomposition PR moves code verbatim and changes no behaviour, and
adding ``reraise_on_credit_or_bug`` here changes what escapes a heavy-pass
cycle under credit exhaustion. Filed as #11664; drop the markers with the fix.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"

REQUIRED_GUARD = "reraise_on_credit_or_bug"

#: The method that owned both sites in the issue findings, and the file it
#: lives in today. One entry per (module, method) — the two handlers inside it
#: are checked together, since both must carry the guard.
INGESTION_SITE = (
    "health_monitor_loop/_heavy.py",
    "_run_harness_suggestion_ingestion_cycle",
)

#: Every known site from the issue, as (module, enclosing method, description).
KNOWN_UNGUARDED_SITES: list[tuple[str, str, str]] = [
    (
        *INGESTION_SITE,
        "except Exception blocks in harness suggestion ingestion",
    ),
]


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _except_exception_handlers(tree: ast.AST) -> list[ast.ExceptHandler]:
    """Return all ``except Exception`` handler nodes in *tree*."""
    handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            handlers.append(node)
    return handlers


def _handler_calls_reraise_guard(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler body calls ``reraise_on_credit_or_bug``."""
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == REQUIRED_GUARD:
            return True
        if isinstance(func, ast.Attribute) and func.attr == REQUIRED_GUARD:
            return True
    return False


def _method_node(filepath: Path, method: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Return the ``def``/``async def`` named *method* in *filepath*."""
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == method
        ):
            return node
    raise AssertionError(
        f"{filepath.name} no longer defines {method}() — the guard has lost its "
        "anchor and would pass vacuously. Re-point it at the method's new home."
    )


def _unguarded_handlers(
    filepath: Path, method: str
) -> list[tuple[int, ast.ExceptHandler]]:
    """Return ``(lineno, handler)`` pairs for every ``except Exception`` inside
    *method* that does **not** call ``reraise_on_credit_or_bug``.
    """
    return [
        (h.lineno, h)
        for h in _except_exception_handlers(_method_node(filepath, method))
        if not _handler_calls_reraise_guard(h)
    ]


# ---------------------------------------------------------------------------
# AST-based: verify source has the guard
# ---------------------------------------------------------------------------


class TestSiteAnchorsStillResolve:
    """The anti-vacuity tripwire, deliberately UNMARKED.

    The checks below are ``xfail`` until the #6855 fix lands (#11664), and
    ``xfail`` swallows EVERY exception in the body — including the
    ``AssertionError`` ``_method_node`` raises when the anchor is gone, and
    the ``filepath.exists()`` assert. Left inside a marked test, the guard
    written to prevent this file from passing vacuously would itself be unable
    to turn the suite red: the same failure mode, one layer up.

    So anchor resolution lives here, unmarked. If the module or the method is
    renamed or moved, THIS reddens, whatever the xfails do.
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
        assert _method_node(filepath, method) is not None

    def test_the_anchor_still_encloses_broad_handlers(self) -> None:
        """The method must still CONTAIN the handlers this file is about.

        Existing is not enough: if the two ``except Exception`` blocks were
        refactored out of this method into a helper, every check below would
        find zero handlers and read as "fixed" when nothing was fixed.
        """
        module, method = INGESTION_SITE
        handlers = _except_exception_handlers(_method_node(SRC / module, method))
        assert handlers, (
            f"{method}() no longer contains any ``except Exception`` block. "
            "Either the fix landed (drop the xfail markers and this guard's "
            "premise) or the handlers moved and the checks are now vacuous."
        )


class TestHealthMonitorSuggestionIngestionBlocksHaveReraise:
    """AST check — the ``except Exception`` blocks surrounding harness
    suggestion ingestion in health_monitor_loop.py must call
    ``reraise_on_credit_or_bug``.
    """

    @pytest.mark.xfail(
        reason="#6855 guard never landed; re-anchored off rotted line windows "
        "in #11547 batch 4 — tracked by #11664. strict=True so landing the fix "
        "forces the marker off instead of silently XPASSing.",
        strict=True,
    )
    def test_suggestion_ingestion_except_blocks_have_reraise_guard(self) -> None:
        module, method = INGESTION_SITE
        unguarded = _unguarded_handlers(SRC / module, method)

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
    @pytest.mark.xfail(
        reason="#6855 guard never landed; re-anchored off rotted line windows "
        "in #11547 batch 4 — tracked by #11664. strict=True so landing the fix "
        "forces the marker off instead of silently XPASSing.",
        strict=True,
    )
    def test_known_site_has_reraise_guard(
        self, filename: str, method: str, desc: str
    ) -> None:
        nearby = [ln for ln, _ in _unguarded_handlers(SRC / filename, method)]

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
    """

    @pytest.fixture()
    def suggestions_dir(self, tmp_path: Path) -> Path:
        """Create a harness_suggestions.jsonl with one valid suggestion."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        jsonl = memory_dir / "harness_suggestions.jsonl"
        jsonl.write_text(
            '{"suggestion":"test principle","title":"test","occurrences":1,'
            '"category":"test_cat"}\n',
            encoding="utf-8",
        )
        return tmp_path

    @pytest.mark.asyncio()
    @pytest.mark.xfail(
        reason="Regression for issue #6855 — fix not yet landed", strict=False
    )
    async def test_authentication_error_propagates(
        self, suggestions_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AuthenticationError from file_memory_suggestion must not be
        swallowed — it should propagate so the orchestrator can handle it.
        """
        from unittest.mock import AsyncMock

        from subprocess_util import AuthenticationError

        loop = _make_health_monitor(suggestions_dir)

        # Patch file_memory_suggestion to raise AuthenticationError
        mock_fms = AsyncMock(side_effect=AuthenticationError("token expired"))
        monkeypatch.setattr("memory.file_memory_suggestion", mock_fms)

        with pytest.raises(AuthenticationError):
            await loop._do_work()

    @pytest.mark.asyncio()
    @pytest.mark.xfail(
        reason="Regression for issue #6855 — fix not yet landed", strict=False
    )
    async def test_credit_exhausted_error_propagates(
        self, suggestions_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CreditExhaustedError from file_memory_suggestion must not be
        swallowed — it should propagate so the orchestrator can pause.
        """
        from unittest.mock import AsyncMock

        from subprocess_util import CreditExhaustedError

        loop = _make_health_monitor(suggestions_dir)

        mock_fms = AsyncMock(side_effect=CreditExhaustedError("credits gone"))
        monkeypatch.setattr("memory.file_memory_suggestion", mock_fms)

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
