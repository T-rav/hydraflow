"""Every var `.env.sample` documents is read by something real.

The two existing env-key ratchets both guard the code→registry direction
(`test_config_env_key_coverage`, `test_gateway_env_key_coverage`); nothing
guarded doc→code, which is how eleven dead vars accumulated in `.env.sample`
— the OTel/Honeycomb block outlived its removal (ADR-0055 → Superseded by
ADR-0118) and two phantom combo vars carried a migration note instructing
operators to set values nothing read. This test closes that direction:
every ``UPPER_CASE=`` name the sample documents must be read by the runtime
(config override tables, credentials, docker passthrough, provider keys,
gateway control plane) or sit on the named allowlist below with a reason.
"""

from __future__ import annotations

import re
from pathlib import Path

from config import CREDENTIAL_ENV_KEYS, env_override_keys
from operator_identity import OPERATOR_TOKEN_ENV
from subprocess_util import (
    _DOCKER_ENV_PASSTHROUGH_KEYS,
    GATEWAY_CONTROL_PLANE_ENV_KEYS,
    PROVIDER_CREDENTIAL_ENV_KEYS,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE = _REPO_ROOT / ".env.sample"

# A documented var is a line-leading NAME= (optionally commented out with a
# single leading `#` and indentation). Lowercase names (the canary config-file
# fields shown for contrast) are deliberately not matched.
_VAR_RE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)=")

#: Documented on purpose although no HydraFlow-runtime override reads them.
#: Every entry carries the surface that DOES read it, or the ruling that
#: keeps it documented. Removing a var from `.env.sample` must remove its
#: entry here too (asserted below), so this list cannot rot.
_DOCUMENTED_UNREAD_ALLOWLIST: dict[str, str] = {
    # ADR-0141 D5: an env override would mean clearing the dial disarmed
    # nothing (the disarmed value IS the default). Config-file/settings only;
    # the sample shows the value and says so.
    "HYDRAFLOW_GATEWAY_ENFORCEMENT_CANARY_REPO": "ADR-0141 D5 — deliberately not an env var",
    # #11541: settings-registry fields (src/settings_registry.py); the sample
    # carries an explicit NOTE that uncommenting them does nothing.
    "HYDRAFLOW_DIRECTOR_TURN_TIMEOUT_SECONDS": "#11541 — settings field, env wiring is separate work",
    "HYDRAFLOW_DIRECTOR_SHADOW_USD_BUDGET": "#11541 — settings field, env wiring is separate work",
    "HYDRAFLOW_DIRECTOR_SHADOW_ENABLED": "#11541 — settings field, env wiring is separate work",
    "HYDRAFLOW_DIRECTOR_SHADOW_USD_CEILING": "#11541 — settings field, env wiring is separate work",
    # Read by compose files, not Python: docker-compose.bugsink.yml refuses
    # to start without the first three (`:?set ... in .env`).
    "BUGSINK_SECRET_KEY": "docker-compose.bugsink.yml",
    "BUGSINK_SUPERUSER": "docker-compose.bugsink.yml",
    "BUGSINK_DB_PASSWORD": "docker-compose.bugsink.yml",
    "BUGSINK_PORT": "docker-compose.bugsink.yml",
    "BUGSINK_BASE_URL": "docker-compose.bugsink.yml",
    # Read by the hf.* slash commands' shell (Phase 0 of .claude/commands),
    # never by the runtime; annotated as such in the sample.
    "HYDRAFLOW_GITHUB_ASSIGNEE": "hf.* slash commands",
}

#: The QUICK START contract: deleting any of these from the sample breaks
#: onboarding and must fail here, not be discovered by the next new operator.
_REQUIRED_DOCUMENTED = frozenset(
    {
        "HYDRAFLOW_GITHUB_REPO",
        "HYDRAFLOW_GH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    }
)

_MINIMUM_DOCUMENTED = 25  # non-vacuity floor: the parse must keep seeing the file


def _documented_names() -> list[str]:
    names: list[str] = []
    for line in _SAMPLE.read_text().splitlines():
        match = _VAR_RE.match(line)
        if match:
            names.append(match.group(1))
    return names


def _read_surface() -> frozenset[str]:
    return (
        env_override_keys()
        | CREDENTIAL_ENV_KEYS
        | GATEWAY_CONTROL_PLANE_ENV_KEYS
        | PROVIDER_CREDENTIAL_ENV_KEYS
        | frozenset(_DOCKER_ENV_PASSTHROUGH_KEYS)
        | frozenset({OPERATOR_TOKEN_ENV})
    )


class TestEnvSampleDocumentsReadKeys:
    def test_parse_is_not_vacuous(self) -> None:
        names = _documented_names()
        assert len(names) >= _MINIMUM_DOCUMENTED, (
            f"parsed only {len(names)} names from .env.sample — the regex or "
            "the file moved out from under this guard"
        )

    def test_quick_start_keys_stay_documented(self) -> None:
        missing = _REQUIRED_DOCUMENTED - set(_documented_names())
        assert not missing, (
            f".env.sample no longer documents {sorted(missing)} — the QUICK "
            "START onboarding contract is broken"
        )

    def test_every_documented_var_is_read_or_allowlisted(self) -> None:
        allowed = _read_surface() | set(_DOCUMENTED_UNREAD_ALLOWLIST)
        dead = [name for name in _documented_names() if name not in allowed]
        assert not dead, (
            f".env.sample documents vars nothing reads: {sorted(set(dead))}. "
            "Either wire the var (an override table, CREDENTIAL_ENV_KEYS, the "
            "docker passthrough, the gateway control plane) or, if it is "
            "deliberately documentation-only, add it to "
            "_DOCUMENTED_UNREAD_ALLOWLIST with the surface that reads it."
        )

    def test_allowlist_carries_no_stale_entries(self) -> None:
        documented = set(_documented_names())
        stale = [k for k in _DOCUMENTED_UNREAD_ALLOWLIST if k not in documented]
        assert not stale, (
            f"allowlist entries no longer in .env.sample: {sorted(stale)} — "
            "remove them so the allowlist cannot rot"
        )

    def test_allowlisted_vars_are_not_also_read(self) -> None:
        # An allowlist entry that config later starts reading should graduate
        # out of the allowlist, not shadow the real surface.
        overlap = set(_DOCUMENTED_UNREAD_ALLOWLIST) & _read_surface()
        assert not overlap, (
            f"now read by the runtime, remove from allowlist: {sorted(overlap)}"
        )
