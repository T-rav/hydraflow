"""Tests for Sentry integration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestSentryInit:
    """Tests for _init_sentry in server.py."""

    def test_noop_when_dsn_empty(self) -> None:
        """Should not call sentry_sdk.init when SENTRY_DSN is empty."""
        with (
            patch.dict("os.environ", {"SENTRY_DSN": ""}, clear=False),
            patch("sentry_sdk.init") as mock_init,
        ):
            from server import _init_sentry

            _init_sentry()
            mock_init.assert_not_called()

    def test_initializes_when_dsn_set(self) -> None:
        """Should call sentry_sdk.init with the DSN."""
        with (
            patch.dict(
                "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
            ),
            patch("sentry_sdk.init") as mock_init,
        ):
            from server import _init_sentry

            _init_sentry()
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args[1]
            assert call_kwargs["dsn"] == "https://key@sentry.io/123"


class TestScrubSensitiveData:
    """Tests for the before_send scrubber."""

    def test_scrubs_github_token(self) -> None:
        """Should redact ghp_ tokens from event data."""
        with patch.dict(
            "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
        ):
            from server import _init_sentry

            # Get the scrub function by inspecting the init call
            with patch("sentry_sdk.init") as mock_init:
                _init_sentry()
                before_send = mock_init.call_args[1]["before_send"]

            event = {"message": "Token is ghp_abcdefghijklmnopqrstuvwxyz0123456789"}
            scrubbed = before_send(event, {})
            assert "ghp_" not in scrubbed["message"]
            assert "[REDACTED]" in scrubbed["message"]

    def test_scrubs_nested_dicts(self) -> None:
        """Should scrub tokens in nested structures."""
        with patch.dict(
            "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
        ):
            from server import _init_sentry

            with patch("sentry_sdk.init") as mock_init:
                _init_sentry()
                before_send = mock_init.call_args[1]["before_send"]

            event = {"extra": {"token": "Bearer eyJhbGciOiJSUzI1NiJ9.test"}}
            scrubbed = before_send(event, {})
            assert "eyJ" not in str(scrubbed)


class TestCaptureIfBug:
    """Tests for capture_if_bug helper."""

    def test_captures_type_error(self) -> None:
        """TypeError should be sent to Sentry."""
        with patch("sentry_sdk.capture_exception") as mock_capture:
            from phase_utils import capture_if_bug

            capture_if_bug(TypeError("bad arg"))
            mock_capture.assert_called_once()

    def test_skips_runtime_error(self) -> None:
        """RuntimeError (transient) should become a breadcrumb, not a capture."""
        with (
            patch("sentry_sdk.capture_exception") as mock_capture,
            patch("sentry_sdk.add_breadcrumb") as mock_breadcrumb,
        ):
            from phase_utils import capture_if_bug

            capture_if_bug(RuntimeError("network timeout"))
            mock_capture.assert_not_called()
            mock_breadcrumb.assert_called_once()
