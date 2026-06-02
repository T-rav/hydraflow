"""Screenshot secret scanner — detects obvious secrets in base64-encoded images.

Scans the raw base64 payload for high-entropy token patterns that should never
appear in a screenshot destined for upload.  The scanner inspects the decoded
text representation (not the pixel content) to catch secrets accidentally
rendered as visible text in the dashboard UI.
"""

from __future__ import annotations

# Canonical secret patterns live in ``secret_scrub`` (the single source of truth
# shared with the audit-stream scrubber, ADR-0085 / SEC-AUDIT-003).
from secret_scrub import SECRET_PATTERNS as _SECRET_PATTERNS


def scan_base64_for_secrets(png_base64: str) -> list[str]:
    """Scan a base64-encoded PNG payload for embedded secret patterns.

    Returns a list of matched pattern labels.  An empty list means no
    secrets were detected.

    **Important limitation:** This scan operates on the raw base64 string, not
    the decoded pixel data.  For actual PNG screenshots captured by html2canvas,
    visible text goes through zlib compression before base64 encoding, which
    means rendered secrets will NOT produce recognisable substrings in the
    encoded payload.  This scanner is therefore primarily effective when the
    payload is not a compressed binary (e.g. an SVG data URI, a plain-text
    blob, or a payload erroneously containing a raw token).  The principal
    protection against leaking sensitive UI content is the frontend DOM
    redaction step (redactSensitiveElements), which runs before capture.
    This scanner provides a defence-in-depth backstop for non-PNG payloads.
    """
    matches: list[str] = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(png_base64):
            matches.append(label)
    return matches
