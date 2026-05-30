"""Tests for repo capability detection (GHAS / code-scanning availability)."""

import json

from scripts.gates.capabilities import detect_capabilities


def _gh_returning(meta: dict):
    def fake_gh(*args: str) -> str:
        return json.dumps(meta)

    return fake_gh


def test_public_repo_has_ghas() -> None:
    # Public repos get code scanning for free, so CodeQL is available.
    caps = detect_capabilities("o/r", gh=_gh_returning({"private": False}))
    assert "ghas" in caps


def test_private_without_advanced_security_has_no_ghas() -> None:
    caps = detect_capabilities(
        "o/r", gh=_gh_returning({"private": True, "security_and_analysis": {}})
    )
    assert "ghas" not in caps


def test_private_with_advanced_security_enabled_has_ghas() -> None:
    caps = detect_capabilities(
        "o/r",
        gh=_gh_returning(
            {
                "private": True,
                "security_and_analysis": {"advanced_security": {"status": "enabled"}},
            }
        ),
    )
    assert "ghas" in caps
