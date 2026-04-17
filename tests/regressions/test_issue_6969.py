"""Regression test for issue #6969.

Bug: Both ``orchestrator.py`` (line ~706-711) and ``base_runner.py``
(line ~148-162) wrap Sentry SDK calls in ``except Exception: pass``.
This silently swallows *any* error — not just ``ImportError`` from a
missing optional dependency.  If ``sentry_sdk`` is installed but
``set_tag`` or ``set_context`` raises a non-ImportError (e.g.
``TypeError``, ``RuntimeError`` from SDK misconfiguration), the failure
is invisible.  This makes Sentry configuration bugs undetectable at
startup and at each agent run.

Expected behaviour after fix:
  - ``ImportError`` (sentry_sdk not installed) is still silently
    swallowed — optional dependency semantics preserved.
  - Non-``ImportError`` exceptions from Sentry SDK calls produce a
    ``logger.debug(...)`` entry so operators can diagnose missing tags
    in the Sentry dashboard.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import ast
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parent.parent.parent / "src"


def _find_sentry_except_handlers(filepath: Path) -> list[ast.ExceptHandler]:
    """Return all ``except`` handlers in *filepath* whose ``try`` body
    contains ``import sentry_sdk``.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        # Check whether the try body (or a nested try within it)
        # contains ``import sentry_sdk``.
        has_sentry_import = False
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if alias.name == "sentry_sdk":
                        has_sentry_import = True
        if has_sentry_import:
            handlers.extend(node.handlers)
    return handlers


def _handler_catches_only_import_error(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler catches exactly ``ImportError``."""
    if handler.type is None:
        return False  # bare except:
    if isinstance(handler.type, ast.Name):
        return handler.type.id == "ImportError"
    if isinstance(handler.type, ast.Tuple):
        return all(
            isinstance(elt, ast.Name) and elt.id == "ImportError"
            for elt in handler.type.elts
        )
    return False


def _handler_body_has_logging(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler body contains any call to ``logger.*``
    or ``logging.*`` (i.e. it doesn't silently ``pass``).
    """
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id in ("logger", "logging", "self._log", "log"):
                    return True
            # Also match self._log.debug(...) style
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "self"
            ):
                return True
    return False


# ===========================================================================
# Tests — orchestrator.py
# ===========================================================================


class TestOrchestratorSentryExceptionHandling:
    """orchestrator.py must not use ``except Exception: pass`` around Sentry
    SDK calls — non-ImportError failures must be logged."""

    _filepath = _SRC / "orchestrator.py"

    def test_sentry_handler_catches_import_error_not_exception(self) -> None:
        """The except clause guarding ``import sentry_sdk`` should catch
        ``ImportError``, not the overly broad ``Exception``.

        Current code (buggy):
            except Exception:
                pass

        Expected code (fixed):
            except ImportError:
                pass
            # ... and/or a separate handler that logs non-ImportError failures
        """
        handlers = _find_sentry_except_handlers(self._filepath)
        assert handlers, (
            f"No try/except block with 'import sentry_sdk' found in {self._filepath}"
        )
        for handler in handlers:
            exc_name = ast.dump(handler.type) if handler.type else "bare except"
            assert _handler_catches_only_import_error(handler), (
                f"orchestrator.py: Sentry try/except catches {exc_name} instead of "
                f"ImportError — non-ImportError SDK failures (TypeError, RuntimeError) "
                f"are silently swallowed, making Sentry configuration bugs invisible. "
                f"(line {handler.lineno})"
            )

    def test_sentry_non_import_error_is_logged(self) -> None:
        """If Sentry SDK is installed but set_tag raises a non-ImportError,
        the exception handler must produce a log entry (not ``pass``).

        This verifies the acceptance criterion: 'Non-ImportError Sentry SDK
        failures produce a debug-level log entry'.
        """
        handlers = _find_sentry_except_handlers(self._filepath)
        assert handlers, (
            f"No try/except block with 'import sentry_sdk' found in {self._filepath}"
        )
        for handler in handlers:
            # If it only catches ImportError, pass is fine — no logging needed.
            if _handler_catches_only_import_error(handler):
                continue
            # Otherwise it catches broader exceptions and MUST log them.
            assert _handler_body_has_logging(handler), (
                f"orchestrator.py: Sentry except handler at line {handler.lineno} "
                f"catches exceptions broader than ImportError but body is bare 'pass' "
                f"— non-ImportError SDK failures are silently discarded. "
                f"Expected a logger.debug() call so operators can diagnose missing "
                f"Sentry tags."
            )


# ===========================================================================
# Tests — base_runner.py
# ===========================================================================


class TestBaseRunnerSentryExceptionHandling:
    """base_runner.py must not use ``except Exception: pass`` around Sentry
    SDK calls — non-ImportError failures must be logged."""

    _filepath = _SRC / "base_runner.py"

    def test_sentry_handler_catches_import_error_not_exception(self) -> None:
        """The except clause guarding ``import sentry_sdk`` should catch
        ``ImportError``, not the overly broad ``Exception``.

        Current code (buggy):
            except Exception:
                pass  # Sentry not installed or not initialized

        Expected code (fixed):
            except ImportError:
                pass
        """
        handlers = _find_sentry_except_handlers(self._filepath)
        assert handlers, (
            f"No try/except block with 'import sentry_sdk' found in {self._filepath}"
        )
        for handler in handlers:
            exc_name = ast.dump(handler.type) if handler.type else "bare except"
            assert _handler_catches_only_import_error(handler), (
                f"base_runner.py: Sentry try/except catches {exc_name} instead of "
                f"ImportError — non-ImportError SDK failures (TypeError, RuntimeError) "
                f"are silently swallowed. Comment says 'Sentry not installed or not "
                f"initialized' but the broad catch hides real integration bugs. "
                f"(line {handler.lineno})"
            )

    def test_sentry_non_import_error_is_logged(self) -> None:
        """If Sentry SDK is installed but set_tag/set_context raises a
        non-ImportError, the exception handler must produce a log entry.
        """
        handlers = _find_sentry_except_handlers(self._filepath)
        assert handlers, (
            f"No try/except block with 'import sentry_sdk' found in {self._filepath}"
        )
        for handler in handlers:
            if _handler_catches_only_import_error(handler):
                continue
            assert _handler_body_has_logging(handler), (
                f"base_runner.py: Sentry except handler at line {handler.lineno} "
                f"catches exceptions broader than ImportError but body is bare 'pass' "
                f"— non-ImportError SDK failures are silently discarded. "
                f"Expected a logger.debug() call so operators can diagnose missing "
                f"Sentry tags/context."
            )
