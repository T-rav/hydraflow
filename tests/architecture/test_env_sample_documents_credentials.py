"""Every credential the factory reads is documented in `.env.sample`.

Scoped to CREDENTIALS deliberately. `.env.sample` is a curated subset — 458
keys are declared, ~30 are documented — so a "cover every declared key" guard
would be wrong and would train people to silence it.

Credentials are the set where absence has a specific, silent failure mode: the
feature that needs one does not error, it goes INERT. `SENTRY_DSN` is the worked
example — the exception sensor's whole design is "presence of the DSN is the
switch", so an operator who never learns the variable exists gets a factory that
reports nothing and looks fine doing it. `BUGSINK_API_TOKEN` is the same shape
one layer down: without it the intake files issues with no stack trace, and
triage auto-closes what it cannot classify.

The gap this closes was real: three of ten credential keys were undocumented
when it was written, one of them added the same night.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from config import CREDENTIAL_ENV_KEYS  # noqa: E402

_SAMPLE = _REPO / ".env.sample"


@pytest.fixture(scope="module")
def sample_text() -> str:
    assert _SAMPLE.is_file(), f"{_SAMPLE.name} is missing"
    return _SAMPLE.read_text(encoding="utf-8")


@pytest.mark.parametrize("key", sorted(CREDENTIAL_ENV_KEYS))
def test_every_credential_key_is_documented(key: str, sample_text: str) -> None:
    assert key in sample_text, (
        f"{key} is read by build_credentials() but appears nowhere in "
        ".env.sample. A credential an operator never learns about is a feature "
        "that silently does nothing — add it (commented out is fine)."
    )


def test_the_guard_has_a_non_empty_subject(sample_text: str) -> None:
    """The decoy: an empty credential set would make every check above vacuous."""
    assert len(CREDENTIAL_ENV_KEYS) >= 5, (
        f"only {len(CREDENTIAL_ENV_KEYS)} credential keys declared — if the "
        "registry moved, this guard is now asserting nothing"
    )
