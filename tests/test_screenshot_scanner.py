"""Tests for the screenshot secret scanner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from screenshot_scanner import scan_base64_for_secrets


class TestScanBase64ForSecrets:
    def test_clean_payload_returns_empty(self) -> None:
        """A payload with no secrets returns an empty list."""
        result = scan_base64_for_secrets("iVBORw0KGgoAAAANSUhEUgAA")
        assert result == []

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            pytest.param(
                "some data ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl more data",
                "GitHub PAT (classic)",
                id="github_pat_classic_detected",
            ),
            pytest.param(
                "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop more",
                "GitHub PAT (fine-grained)",
                id="github_pat_fine_grained_detected",
            ),
            pytest.param(
                "AKIAIOSFODNN7EXAMPLE more",
                "AWS access key",
                id="aws_access_key_detected",
            ),
            pytest.param(
                "xoxb-123456789-abcdefghijk more",
                "Slack token",
                id="slack_token_detected",
            ),
            pytest.param(
                "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX more",
                "Anthropic API key",
                id="anthropic_api_key_detected",
            ),
            pytest.param(
                "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIB more",
                "Generic private key",
                id="private_key_header_detected",
            ),
            pytest.param(
                'secret: "my_super_secret_value"',
                "Generic secret assignment",
                id="generic_secret_assignment_detected",
            ),
            pytest.param(
                "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl",
                "GitHub OAuth token",
                id="github_oauth_token_detected",
            ),
            pytest.param(
                "ghu_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl",
                "GitHub App token",
                id="github_app_token_detected",
            ),
            pytest.param(
                "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl",
                "GitHub App installation",
                id="github_app_installation_token_detected",
            ),
            pytest.param(
                "ghr_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl",
                "GitHub refresh token",
                id="github_refresh_token_detected",
            ),
            # OpenSSH headers must land on the same generic-private-key label as PEM.
            pytest.param(
                "-----BEGIN OPENSSH PRIVATE KEY-----\nbase64data",
                "Generic private key",
                id="openssh_private_key_detected",
            ),
            # Upper-case assignment: secret-assignment matching is case-insensitive.
            pytest.param(
                'PASSWORD="supersecretpassword1"',
                "Generic secret assignment",
                id="case_insensitive_secret_assignment",
            ),
        ],
    )
    def test_secret_pattern_detected(self, payload: str, expected: str) -> None:
        """Each supported secret shape is recognised and labelled."""
        result = scan_base64_for_secrets(payload)
        assert expected in result

    def test_openai_api_key_detected(self) -> None:
        """A realistic 48-char OpenAI API key is detected.

        The shared pattern (secret_scrub) is anchored + length-tightened to
        avoid mid-token-corrupting legitimate identifiers when scrubbing the
        audit stream (ADR-0085); real OpenAI keys are 48 chars, so detection of
        a genuine key is unaffected.
        """
        payload = "sk-" + "A1B2C3D4E5" * 4 + "ABCDEFGH more"  # sk- + 48 chars
        result = scan_base64_for_secrets(payload)
        assert "OpenAI API key" in result

    def test_multiple_secrets_returns_all(self) -> None:
        """Multiple different secret types in the same payload are all reported."""
        payload = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl AKIAIOSFODNN7EXAMPLE"
        result = scan_base64_for_secrets(payload)
        assert len(result) >= 2
        assert "GitHub PAT (classic)" in result
        assert "AWS access key" in result

    def test_empty_string_returns_empty(self) -> None:
        """An empty string returns an empty list."""
        result = scan_base64_for_secrets("")
        assert result == []
