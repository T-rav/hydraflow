"""Tests for Sentry integration."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Create a mock sentry_sdk module so tests work even when sentry-sdk
# is not installed in the test environment.
_mock_sentry = MagicMock()

# A hint that marks a real code bug (the only events _before_send keeps).
_BUG_HINT = {"exc_info": (ValueError, ValueError("real bug"), None)}


def _force_before_send():
    """Init Sentry (forced, against the mock SDK) and return its before_send.

    ``force=True`` bypasses the pytest / HYDRAFLOW_SENTRY_DISABLED guard so the
    init machinery runs against the mocked ``sentry_sdk`` and we can capture the
    ``before_send`` callback it was configured with.
    """
    sys.modules.pop("server", None)
    with patch.dict(
        "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
    ):
        from server import _init_sentry

        _mock_sentry.init.reset_mock()
        _init_sentry(force=True)
        return _mock_sentry.init.call_args[1]["before_send"]


@pytest.fixture(autouse=True)
def _ensure_sentry_module():
    """Inject a mock sentry_sdk into sys.modules for all tests."""
    had = "sentry_sdk" in sys.modules
    original = sys.modules.get("sentry_sdk")
    sys.modules["sentry_sdk"] = _mock_sentry

    # Also need sub-modules for the integrations
    sys.modules["sentry_sdk.integrations"] = MagicMock()
    sys.modules["sentry_sdk.integrations.fastapi"] = MagicMock()
    sys.modules["sentry_sdk.integrations.logging"] = MagicMock()

    _mock_sentry.reset_mock()
    yield
    if had:
        sys.modules["sentry_sdk"] = original
    else:
        sys.modules.pop("sentry_sdk", None)
    sys.modules.pop("sentry_sdk.integrations", None)
    sys.modules.pop("sentry_sdk.integrations.fastapi", None)
    sys.modules.pop("sentry_sdk.integrations.logging", None)


class TestSentryInit:
    def test_noop_when_dsn_empty(self) -> None:
        # Force re-import of server to pick up the mock
        sys.modules.pop("server", None)
        with patch.dict("os.environ", {"SENTRY_DSN": ""}, clear=False):
            from server import _init_sentry

            _mock_sentry.init.reset_mock()
            _init_sentry(force=True)
            _mock_sentry.init.assert_not_called()

    def test_initializes_when_dsn_set(self) -> None:
        sys.modules.pop("server", None)
        with patch.dict(
            "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
        ):
            from server import _init_sentry

            _mock_sentry.init.reset_mock()
            _init_sentry(force=True)
            _mock_sentry.init.assert_called_once()
            call_kwargs = _mock_sentry.init.call_args[1]
            assert call_kwargs["dsn"] == "https://key@sentry.io/123"

    def test_skips_init_under_test_suite_even_with_dsn(self) -> None:
        """Without force, a configured DSN must NOT init the real client.

        Tests and MockWorld scenarios use fixture data (issue #42, PR #101,
        "boom"); shipping it to production Sentry was the root cause of the bulk
        of the noise. The guard trips on pytest being imported and on the
        HYDRAFLOW_SENTRY_DISABLED kill-switch conftest sets for the whole suite.
        """
        sys.modules.pop("server", None)
        with patch.dict(
            "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
        ):
            from server import _init_sentry

            _mock_sentry.init.reset_mock()
            _init_sentry()  # no force → guard should block init
            _mock_sentry.init.assert_not_called()

    def test_disabled_kill_switch_blocks_init(self) -> None:
        """HYDRAFLOW_SENTRY_DISABLED=1 is an explicit deploy-time kill-switch."""
        sys.modules.pop("server", None)
        with patch.dict(
            "os.environ",
            {
                "SENTRY_DSN": "https://key@sentry.io/123",
                "HYDRAFLOW_SENTRY_DISABLED": "1",
            },
            clear=False,
        ):
            from server import _init_sentry

            _mock_sentry.init.reset_mock()
            _init_sentry()
            _mock_sentry.init.assert_not_called()


class TestScrubSensitiveData:
    def test_scrubs_github_token(self) -> None:
        before_send = _force_before_send()
        event = {"message": "Token is ghp_abcdefghijklmnopqrstuvwxyz0123456789"}
        scrubbed = before_send(event, dict(_BUG_HINT))
        assert scrubbed is not None
        assert "ghp_" not in scrubbed["message"]
        assert "[REDACTED]" in scrubbed["message"]

    def test_scrubs_nested_dicts(self) -> None:
        before_send = _force_before_send()
        event = {"extra": {"token": "Bearer eyJhbGciOiJSUzI1NiJ9.test"}}
        scrubbed = before_send(event, dict(_BUG_HINT))
        assert scrubbed is not None
        assert "eyJ" not in str(scrubbed)


class TestBeforeSendBugsOnly:
    """``_before_send`` keeps only real code bugs — the documented contract.

    Operational noise (message-only ``logger.error`` / ``capture_message`` and
    transient/infra exceptions) is dropped so it never reaches Sentry.
    """

    def test_drops_message_only_event(self) -> None:
        before_send = _force_before_send()
        event = {"message": "GitHub API rate limit hit; backing off"}
        assert before_send(event, {}) is None

    def test_drops_message_only_log_record(self) -> None:
        before_send = _force_before_send()
        record = SimpleNamespace(exc_info=None)
        event = {"message": "gh issue list failed for label='hydraflow-hitl'"}
        assert before_send(event, {"log_record": record}) is None

    def test_drops_transient_exception(self) -> None:
        before_send = _force_before_send()
        hint = {"exc_info": (RuntimeError, RuntimeError("subprocess boom"), None)}
        assert before_send({"message": "boom"}, hint) is None

    def test_keeps_bug_exception_and_fingerprints(self) -> None:
        before_send = _force_before_send()
        hint = {"exc_info": (TypeError, TypeError("bad type"), None)}
        kept = before_send({"message": "real bug"}, hint)
        assert kept is not None
        assert kept["fingerprint"][0] == "TypeError"

    def test_keeps_bug_logged_with_exc_info(self) -> None:
        before_send = _force_before_send()
        record = SimpleNamespace(exc_info=(KeyError, KeyError("missing key"), None))
        kept = before_send({"message": "logged bug"}, {"log_record": record})
        assert kept is not None
        assert kept["fingerprint"][0] == "KeyError"


class TestCaptureIfBug:
    def test_captures_type_error(self) -> None:
        """TypeError should be sent to Sentry."""
        from exception_classify import capture_if_bug

        _mock_sentry.capture_exception.reset_mock()
        capture_if_bug(TypeError("bad arg"))
        _mock_sentry.capture_exception.assert_called_once()

    def test_skips_runtime_error(self) -> None:
        """RuntimeError (transient) should become a breadcrumb, not a capture."""
        from exception_classify import capture_if_bug

        _mock_sentry.capture_exception.reset_mock()
        _mock_sentry.add_breadcrumb.reset_mock()
        capture_if_bug(RuntimeError("network timeout"))
        _mock_sentry.capture_exception.assert_not_called()
        _mock_sentry.add_breadcrumb.assert_called_once()


class TestSentryTransactionHelper:
    def test_noop_when_sentry_not_available(self) -> None:
        # Temporarily hide sentry_sdk from sys.modules
        sys.modules.pop("phase_utils", None)
        original = sys.modules.pop("sentry_sdk", None)
        try:
            from phase_utils import _sentry_transaction

            with _sentry_transaction("test.op", "test:name"):
                pass  # should not raise
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original

    def test_starts_transaction_when_sentry_available(self) -> None:
        sys.modules.pop("phase_utils", None)
        # Set up mock transaction context manager
        mock_txn = MagicMock()
        mock_txn.__enter__ = MagicMock(return_value=mock_txn)
        mock_txn.__exit__ = MagicMock(return_value=False)
        _mock_sentry.start_transaction.return_value = mock_txn
        _mock_sentry.start_transaction.reset_mock()

        from phase_utils import _sentry_transaction

        with _sentry_transaction("test.op", "test:name"):
            pass

        _mock_sentry.start_transaction.assert_called_once_with(
            op="test.op", name="test:name"
        )

    def test_passes_op_and_name_to_transaction(self) -> None:
        sys.modules.pop("phase_utils", None)
        mock_txn = MagicMock()
        mock_txn.__enter__ = MagicMock(return_value=mock_txn)
        mock_txn.__exit__ = MagicMock(return_value=False)
        _mock_sentry.start_transaction.return_value = mock_txn

        from phase_utils import _sentry_transaction

        with _sentry_transaction("pipeline.plan", "plan:#99"):
            pass

        call_kwargs = _mock_sentry.start_transaction.call_args[1]
        assert call_kwargs["op"] == "pipeline.plan"
        assert call_kwargs["name"] == "plan:#99"
