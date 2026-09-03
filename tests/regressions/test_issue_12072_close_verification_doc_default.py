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

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from config import HydraFlowConfig  # noqa: E402

_FIELD = "close_verification_enabled"
_SRC = Path(__file__).parents[2] / "src"

#: PROSE phrases asserting the actuator is off unless someone turns it on.
#:
#: `default=false` is deliberately NOT here. It matches the field's own source
#: line (`default=False,`), so including it made the "docs say off" branch
#: below satisfiable by the code rather than by any documentation — a branch
#: that could never fail. Caught by flipping the default and watching nothing
#: redden.
_CLAIMS_OFF = (
    "default-off",
    "default false",
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


def test_the_documentation_matches_the_shipped_default() -> None:
    """The docs must describe whichever default the field actually ships.

    Asserted in BOTH directions with no skip: an earlier version skipped when
    the default was False, which the no-ignored-active-tests ratchet correctly
    refuses — a guard that opts out of asserting is not a guard.
    """
    text = _documenting_text()
    claims_off = [claim for claim in _CLAIMS_OFF if claim in text]

    if HydraFlowConfig.model_fields[_FIELD].default is True:
        assert not claims_off, (
            f"`{_FIELD}` ships default=True but its documentation still claims "
            f"{claims_off}. This actuator reopens and re-triages issues, so "
            f"the wrong answer here is the unsafe one."
        )
    else:
        assert claims_off, (
            f"`{_FIELD}` ships default=False but nothing in its documentation "
            f"says so; a reader would assume the actuator is live."
        )


def test_the_documentation_names_the_disable_path() -> None:
    """Default-ON is only safe to document if the way OUT is documented too."""
    text = _documenting_text()

    assert "system tab" in text or "close_verification_enabled=false" in text, (
        "a default-ON actuator must document how to turn it off"
    )
