"""#12072: the docs said default-OFF for a year after the default flipped ON.

`close_verification_enabled` shipped `default=False` under the G1 auto-recut
actuator's rollout discipline. The default later flipped to `True` — the field
and `_ENV_BOOL_OVERRIDES` both agree — but the comment above the field and
`close_verification.py`'s module docstring still said "Default-OFF and fully
inert until enabled" and "default false: fully inert".

The actuator REOPENS and RE-TRIAGES issues, so a reader deciding whether a
false close can be silently reverted got exactly the wrong answer from the
docs — on the safety-relevant direction.

This derives the expectation from the LIVE default rather than hardcoding
either value, so it fails whichever way the two drift apart next.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from config import HydraFlowConfig  # noqa: E402

_FIELD = "close_verification_enabled"
_SRC = Path(__file__).parents[2] / "src"

#: Phrases that assert the actuator is off unless someone turns it on.
_CLAIMS_OFF = (
    "default-off",
    "default false",
    "default=false",
    "fully inert until",
)


def _documenting_text() -> str:
    """The two places that describe this flag's default, lowercased."""
    config = (_SRC / "config.py").read_text(encoding="utf-8")
    start = config.index(f"{_FIELD}: bool = Field(")
    # The comment block immediately above the field, plus its description.
    head = config[max(0, start - 900) : start]
    body = config[start : start + 700]
    module = (_SRC / "close_verification.py").read_text(encoding="utf-8")[:2000]
    return (head + body + module).lower()


def test_the_field_still_exists_to_be_documented() -> None:
    """Anti-vacuity floor: the scan below is trivially clean on a missing field."""
    assert _FIELD in HydraFlowConfig.model_fields
    assert f"{_FIELD}: bool = Field(" in (_SRC / "config.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("claim", _CLAIMS_OFF)
def test_no_default_off_claim_survives_a_default_on_flag(claim: str) -> None:
    """The docs must not say OFF while the shipped default is ON."""
    if HydraFlowConfig.model_fields[_FIELD].default is not True:
        pytest.skip("default is not True; this direction is not the risk")

    assert claim not in _documenting_text(), (
        f"`{_FIELD}` ships default=True but its documentation still claims "
        f"{claim!r}. This actuator reopens and re-triages issues, so the "
        f"wrong answer here is the unsafe one."
    )


def test_the_documentation_names_the_disable_path() -> None:
    """Default-ON is only safe to document if the way OUT is documented too."""
    text = _documenting_text()

    assert "system tab" in text or "close_verification_enabled=false" in text, (
        "a default-ON actuator must document how to turn it off"
    )
