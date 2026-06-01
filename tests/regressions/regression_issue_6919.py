"""Regression test for issue #6919.

Bug: ``BeadsManager._parse_ready_json`` and ``_parse_show_json`` call
``json.loads(output)`` directly with no ``JSONDecodeError`` guard.  When
the ``bd`` CLI returns a non-JSON error message (e.g. Dolt server not
running, npm link broken), the exception propagates uncaught and crashes
every caller that uses beads task decomposition (plan_phase).

Expected behaviour after fix:
  - ``_parse_ready_json`` returns ``[]`` (with ``logger.warning``) on
    non-JSON ``bd`` output.
  - ``_parse_show_json`` returns ``None`` (with ``logger.warning``) on
    non-JSON ``bd`` output.

These tests assert the *correct* behaviour, so they are RED against the
current (buggy) code.
"""

from __future__ import annotations

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from beads_manager import BeadsManager

# --- Realistic malformed bd CLI outputs ---

# bd CLI prints a plain error string when dolt isn't running
DOLT_NOT_RUNNING = (
    "Error: connect ECONNREFUSED 127.0.0.1:3306 - Dolt server is not running"
)

# bd CLI emits a partial/corrupt JSON blob
TRUNCATED_JSON = '[{"id": "beads-test-4yu", "title": "do thing"'

# bd CLI emits an HTML error page (proxy misconfiguration)
HTML_ERROR = "<html><body><h1>502 Bad Gateway</h1></body></html>"

# Empty string — bd CLI exited with no output
EMPTY_OUTPUT = ""


class TestParseReadyJsonMalformedInput:
    """_parse_ready_json must return [] on non-JSON input, not raise."""

    @pytest.mark.xfail(reason="Regression for issue #6919 — fix not yet landed", strict=False)
    def test_plain_error_string(self) -> None:
        result = BeadsManager._parse_ready_json(DOLT_NOT_RUNNING)
        assert result == []

    @pytest.mark.xfail(reason="Regression for issue #6919 — fix not yet landed", strict=False)
    def test_truncated_json(self) -> None:
        result = BeadsManager._parse_ready_json(TRUNCATED_JSON)
        assert result == []

    @pytest.mark.xfail(reason="Regression for issue #6919 — fix not yet landed", strict=False)
    def test_html_error(self) -> None:
        result = BeadsManager._parse_ready_json(HTML_ERROR)
        assert result == []

    @pytest.mark.xfail(reason="Regression for issue #6919 — fix not yet landed", strict=False)
    def test_empty_output(self) -> None:
        result = BeadsManager._parse_ready_json(EMPTY_OUTPUT)
        assert result == []


class TestParseShowJsonMalformedInput:
    """_parse_show_json must return None on non-JSON input, not raise."""

    @pytest.mark.xfail(reason="Regression for issue #6919 — fix not yet landed", strict=False)
    def test_plain_error_string(self) -> None:
        result = BeadsManager._parse_show_json(DOLT_NOT_RUNNING)
        assert result is None

    @pytest.mark.xfail(reason="Regression for issue #6919 — fix not yet landed", strict=False)
    def test_truncated_json(self) -> None:
        result = BeadsManager._parse_show_json(TRUNCATED_JSON)
        assert result is None

    @pytest.mark.xfail(reason="Regression for issue #6919 — fix not yet landed", strict=False)
    def test_html_error(self) -> None:
        result = BeadsManager._parse_show_json(HTML_ERROR)
        assert result is None

    @pytest.mark.xfail(reason="Regression for issue #6919 — fix not yet landed", strict=False)
    def test_empty_output(self) -> None:
        result = BeadsManager._parse_show_json(EMPTY_OUTPUT)
        assert result is None
