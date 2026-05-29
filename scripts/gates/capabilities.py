"""Detect repo capabilities that gate which tool binds to a guardrail dimension.

Currently one capability: ``ghas`` (GitHub Advanced Security / code scanning).
A private repo without GHAS cannot run CodeQL, so the resolver must fall back to
an OSS binding (Semgrep, bandit) for the SAST dimension. Public repos get code
scanning for free, so they are treated as ``ghas``-capable.

The probe is injectable (``gh``) so it is unit-testable without the network.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable


def _run_gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return result.stdout


def detect_capabilities(
    repo: str, *, gh: Callable[..., str] = _run_gh
) -> frozenset[str]:
    """Capabilities for ``repo`` (owner/name). Currently ``{"ghas"}`` or ``set()``."""
    meta = json.loads(gh("api", f"/repos/{repo}"))
    caps: set[str] = set()
    if not meta.get("private", False):
        caps.add("ghas")
    else:
        saa = meta.get("security_and_analysis") or {}
        if (saa.get("advanced_security") or {}).get("status") == "enabled":
            caps.add("ghas")
    return frozenset(caps)
