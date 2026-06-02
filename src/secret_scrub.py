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
