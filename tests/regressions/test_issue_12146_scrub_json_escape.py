"""#12146: scrubbing must not delete the escape that keeps a quote in a string.

``AuditChain._scrub_payload`` scrubs the SERIALIZED JSON of a payload and then
re-parses it. Three patterns used a negated value class that excluded the quote
but not the backslash, so a greedy match ate the value *plus its escaping
backslash* and stopped at the quote. Replacing that run left a bare ``"`` which
closed the JSON string early, and ``json.loads`` raised -- crashing every one of
the thirteen ``AuditChain`` writers, on the branch where a redaction actually
happened.

The pattern's own comment claimed it already prevented this: it enumerated the
JSON structural characters and missed that the escape is structural too.
"""

from __future__ import annotations

import json

import pytest

from secret_scrub import SECRET_PATTERNS, scrub_secrets

#: One genuine positive per pattern label. Each is asserted to actually match
#: its own pattern below, so a probe that silently stopped matching cannot make
#: the round-trip assertion pass vacuously.
_PROBES: dict[str, str] = {
    "GitHub PAT (classic)": "ghp_" + "A" * 36,
    "GitHub PAT (fine-grained)": "github_pat_" + "A" * 40,
    "GitHub OAuth token": "gho_" + "A" * 36,
    "GitHub App token": "ghu_" + "A" * 36,
    "GitHub App installation": "ghs_" + "A" * 36,
    "GitHub refresh token": "ghr_" + "A" * 36,
    "AWS access key": "AKIA" + "B" * 16,
    "AWS secret key": "secret_key=" + "A" * 25,
    "Slack token": "xoxb-" + "A" * 20,
    "Anthropic API key": "sk-ant-" + "A" * 20,
    "OpenAI API key": " sk-" + "A" * 40,
    "HydraFlow gateway virtual key": "hfgw_" + "A" * 8 + "." + "A" * 20,
    "HydraFlow gateway control token (assignment)": "GATEWAY_CONTROL_TOKEN=" + "A" * 16,
    "HydraFlow gateway control token": "hfgwctl_" + "A" * 32,
    "HydraFlow operator token (assignment)": "OPERATOR_TOKEN=" + "A" * 16,
    "HydraFlow operator token": "hfop_" + "A" * 32,
    "Generic private key": "-----BEGIN RSA PRIVATE KEY-----",
    "Generic secret assignment": 'password="' + "A" * 12 + '"',
}

_LABELS = [label for label, _ in SECRET_PATTERNS]


def test_every_pattern_has_a_probe() -> None:
    """Iterating SECRET_PATTERNS by reference is only a guard if it is total.

    A pattern added without a probe would otherwise be silently unexercised --
    the gap this whole issue is about, one level up.
    """
    assert set(_LABELS) == set(_PROBES), (
        "SECRET_PATTERNS and _PROBES disagree; add a probe for a new pattern "
        "rather than letting it go unexercised"
    )


@pytest.mark.parametrize("label", _LABELS)
def test_probe_is_a_genuine_positive(label: str) -> None:
    """Anti-vacuity: the probe must actually match the pattern it stands for."""
    pattern = dict(SECRET_PATTERNS)[label]
    assert pattern.search(_PROBES[label]), (
        f"probe for {label!r} no longer matches its pattern, so the round-trip "
        f"test below proves nothing about it"
    )


@pytest.mark.parametrize("label", _LABELS)
def test_scrubbing_serialized_json_stays_parseable(label: str) -> None:
    """The defect: a secret beside an escaped quote must survive the round trip.

    ``"deploy"`` supplies the escaped quote. In serialized JSON it arrives as
    ``\\"``, and a value class that excludes the quote but not the backslash
    consumes the escape and leaves the quote closing the string early.
    """
    secret = _PROBES[label]
    line = json.dumps({"body": f'{secret}"deploy" notes'})
    scrubbed = scrub_secrets(line)

    assert scrubbed != line, f"{label!r} was not redacted at all"
    json.loads(scrubbed)  # must not raise
    assert secret.strip() not in scrubbed, f"{label!r} survived the scrub"


@pytest.mark.parametrize("keyword", ["password", "secret", "token", "api_key"])
def test_an_unbalanced_quote_does_not_corrupt_the_record(keyword: str) -> None:
    """The regression the FIRST fix introduced, found in review of #12149.

    Making the quoted pattern tolerate a JSON escape with `\\\\?` on each side
    independently was wrong in the same way #12146 itself was wrong. Given an
    unbalanced quote — an ordinary human typo in a PR title — the opener
    consumed the escape, the value class ran past it to the field's own
    STRUCTURAL closing quote, and the trailing `\\\\?['\\"]` ate that too:

        {"body": "password=\\"never rotated"}
          -> {"body": "[REDACTED:Generic secret assignment]}
          -> JSONDecodeError: Unterminated string

    Requiring the delimiters to MATCH means an unbalanced quote simply fails to
    match. Fail safe, not fail corrupt: the occurrence is left unredacted rather
    than the record being destroyed. Nothing is leaked that a matching pattern
    would have caught, because there is no closing delimiter to bound it.
    """
    line = json.dumps({"body": f'{keyword}="never rotated', "z": "tail"})

    scrubbed = scrub_secrets(line)

    json.loads(scrubbed)  # must not raise


def test_an_unbalanced_quote_still_lets_a_LATER_balanced_secret_be_caught() -> None:
    """Failing to match one occurrence must not blind the scrubber to the next."""
    secret = "Z" * 14
    line = json.dumps({"a": 'password="unterminated', "b": f'password="{secret}"'})

    scrubbed = scrub_secrets(line)

    json.loads(scrubbed)
    assert secret not in scrubbed, "the balanced secret after it must still redact"
