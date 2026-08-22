"""Canonical secret patterns + scrubber for HydraFlow.

Single source of truth for credential-shaped strings. Used by:

- ``file_util.append_jsonl`` — scrubs every record on the canonical
  audit/transcript/event JSONL write path, so a leaked token (e.g. a failing
  ``gh`` command echoing ``GH_TOKEN``, or an agent pasting an env dump) never
  reaches the durable, fanned-out audit stream. See ADR-0085.
- ``screenshot_scanner`` — detects secrets in upload-bound payloads.

The detect/scrub split: ``scan_for_secrets`` returns the labels found (for
flagging); ``scrub_secrets`` replaces each match with a labelled redaction
marker (for the persistence boundary). Patterns require specific structure
(known prefixes, quoted assignments) to keep false-positive redaction of
legitimate audit prose low.
"""

from __future__ import annotations

import re

# (label, compiled regex). Specific-prefix / structured patterns only.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GitHub PAT (classic)", re.compile(r"ghp_[A-Za-z0-9]{36,}")),
    ("GitHub PAT (fine-grained)", re.compile(r"github_pat_[A-Za-z0-9_]{40,}")),
    ("GitHub OAuth token", re.compile(r"gho_[A-Za-z0-9]{36,}")),
    ("GitHub App token", re.compile(r"ghu_[A-Za-z0-9]{36,}")),
    ("GitHub App installation", re.compile(r"ghs_[A-Za-z0-9]{36,}")),
    ("GitHub refresh token", re.compile(r"ghr_[A-Za-z0-9]{36,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "AWS secret key",
        # Value class excludes whitespace AND JSON structural chars (quote,
        # comma, brace) so the greedy match can't cross a string boundary and
        # corrupt the serialized JSON line append_jsonl scrubs. IGNORECASE also
        # catches the uppercase AWS_SECRET_ACCESS_KEY=... env-var form.
        re.compile(
            r"(?:aws_secret_access_key|secret_key)\s*[:=]\s*[^\s'\",}]{20,}",
            re.IGNORECASE,
        ),
    ),
    ("Slack token", re.compile(r"xox[bporas]-[A-Za-z0-9\-]+")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}")),
    # Anchored (not preceded by word-char/hyphen) + length closer to a real
    # 48-char key, so it doesn't mid-token-corrupt legitimate identifiers like
    # `disk-1a2b...` or `task-sk-...` on the irreversible audit-write path.
    # (sk-ant- runs earlier and is matched first.)
    ("OpenAI API key", re.compile(r"(?<![\w-])sk-[A-Za-z0-9]{40,}")),
    # --- HydraFlow LLM gateway credentials (ADR-0138) ---------------------
    # The virtual key is the credential every gateway-routed worker spawn holds
    # in ANTHROPIC_AUTH_TOKEN, so an echoed child env leaks it straight onto this
    # write path. Grammar read from hydraflow_gateway/keys.py::VirtualKeyStore.mint:
    # f"hfgw_{key_id}.{secret}", key_id = str(ULID()) (26 Crockford base32 chars,
    # rejected if it contains "."), secret = secrets.token_urlsafe(32) (43 url-safe
    # chars). BOTH halves plus the dot are required: ADR-0138's read plane
    # publishes a bare key_id on purpose, and append_jsonl is append-only, so a
    # pattern that could eat one would destroy published content irreversibly.
    # The floors sit below the real lengths (a custom id_factory still matches)
    # but far above "hfgw_x.md"-shaped prose. The value class excludes whitespace
    # and JSON structural chars, so a match can never cross a string boundary and
    # corrupt the serialized line.
    #
    # The key_id half is CEILINGED at 64 (2.5x a ULID) and that ceiling is
    # load-bearing, not decoration. Unbounded, this pattern is quadratic on
    # attacker-shaped input: every "hfgw_" is a start position, the greedy class
    # eats the rest of the record, then backtracks one char at a time hunting the
    # required ".". A record of stacked "hfgw_" prefixes cost 1.1s at 80 KB and
    # grows 4x per doubling — and ADR-0085's threat model is explicitly
    # attacker-triggerable (a crafted issue inducing an agent to echo the child
    # env, ADR-0092), on the write path EVERY loop calls. The ceiling caps the
    # scan per start position, making it linear: 2.3ms at the same 80 KB.
    # The secret half stays unbounded on purpose — it only runs once a prefix has
    # already matched, so it cannot blow up, and a ceiling there could redact just
    # the first N chars of an over-long secret and leave the tail exposed.
    (
        "HydraFlow gateway virtual key",
        re.compile(r"hfgw_[A-Za-z0-9_-]{8,64}\.[A-Za-z0-9_-]{20,}"),
    ),
    # The control token has no minter: settings.py accepts any >=32-byte ASCII
    # header value, so a legacy token is only recognisable by the variable it is
    # bound to. This catches the realistic leak — an UNQUOTED env dump, which the
    # quoted-only "Generic secret assignment" pattern below cannot see. Bracket
    # chars are excluded from the value class alongside the JSON structural set so
    # the pattern can never re-match a [REDACTED:...] marker, keeping scrubbing
    # idempotent whatever order these patterns run in.
    (
        "HydraFlow gateway control token (assignment)",
        re.compile(
            r"(?:HYDRAFLOW_)?GATEWAY_CONTROL_TOKEN\s*[:=]\s*[^\s'\",}\[\]]{16,}",
            re.IGNORECASE,
        ),
    ),
    # A control token minted in the canonical gateway/README.md grammar --
    # "hfgwctl_" + secrets.token_urlsafe(32) -- is detectable on its own, with no
    # variable name nearby. The prefix deliberately does not collide with the
    # virtual key's "hfgw_" (the character after "hfgw" differs), so neither
    # pattern can mislabel the other's tokens.
    (
        "HydraFlow gateway control token",
        re.compile(r"hfgwctl_[A-Za-z0-9_-]{32,}"),
    ),
    # The dashboard operator credential ADR-0140 gates policy writes on. Same
    # shape of rule as the two gateway tokens above and here for the same reason:
    # a credential that only the "not in payload" assertion in one test file can
    # catch is a credential the canonical detector is blind to everywhere else —
    # the audit chain and the transcript stream included. The "hfop_" prefix
    # collides with neither "hfgw_" nor "hfgwctl_".
    (
        "HydraFlow operator token (assignment)",
        re.compile(
            r"(?:HYDRAFLOW_)?OPERATOR_TOKEN\s*[:=]\s*[^\s'\",}\[\]]{16,}",
            re.IGNORECASE,
        ),
    ),
    (
        "HydraFlow operator token",
        re.compile(r"hfop_[A-Za-z0-9_-]{32,}"),
    ),
    (
        "Generic private key",
        re.compile(r"-----BEGIN\s+(RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "Generic secret assignment",
        re.compile(
            r"(?:secret|password|token|api_key)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
            re.IGNORECASE,
        ),
    ),
]


def scan_for_secrets(text: str) -> list[str]:
    """Return the labels of every secret pattern found in *text* (empty = none)."""
    return [label for label, pattern in SECRET_PATTERNS if pattern.search(text)]


def scrub_secrets(text: str) -> str:
    """Replace credential-shaped substrings with a labelled redaction marker.

    Idempotent: the ``[REDACTED:...]`` markers it emits do not match any pattern.
    The markers contain no JSON-breaking characters, so scrubbing a serialized
    JSON line keeps it valid.
    """
    for label, pattern in SECRET_PATTERNS:
        text = pattern.sub(f"[REDACTED:{label}]", text)
    return text
