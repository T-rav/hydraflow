"""Gateway credentials must not survive the durable audit write (issue #11635).

``secret_scrub.SECRET_PATTERNS`` is the canonical set behind ADR-0085 ("secrets
never persist in the audit stream"), and ``file_util.append_jsonl`` applies it to
every record on the durable audit/transcript/event JSONL path. Before this fix it
had no pattern for either gateway credential, so a virtual key an agent echoed
(``ANTHROPIC_AUTH_TOKEN`` on every gateway-routed worker spawn) persisted verbatim
into a retained, fanned-out stream.

The virtual-key case here is deliberately driven by the *real* minter
(``hydraflow_gateway.keys.VirtualKeyStore``) rather than a hand-written literal:
if the mint grammar in ``keys.py`` ever drifts away from the pattern, this test
fails instead of the scrubber silently going blind again.

The negative half matters just as much. ``append_jsonl`` is append-only — there is
no un-redacting — and ADR-0138's read plane publishes ``key_id`` on purpose, so a
pattern that ate a bare ``key_id`` would destroy published, legitimate content.
"""

from __future__ import annotations

import json
from pathlib import Path

from file_util import append_jsonl
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.models import MintKeyRequest, ProviderBinding, RepoClass
from secret_scrub import scan_for_secrets, scrub_secrets

# Canonical control-token grammar (gateway/README.md): the ``hfgwctl_`` prefix
# plus ``secrets.token_urlsafe(32)``.
_CONTROL_TOKEN = "hfgwctl_" + "Zq3-tN7wR1cP0sV8yB2xL5mK9jH4dF6g_A"


def _mint_real_virtual_key() -> str:
    """Mint a token through the production ``VirtualKeyStore`` code path."""
    store = VirtualKeyStore(max_ttl_seconds=600)
    minted = store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id="implementer",
            spawn_id="spawn-1",
            session_id="session-1",
            issue_number=11635,
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ANTHROPIC,
            capture_bodies=False,
            ttl_seconds=300,
        )
    )
    return minted.token


def test_minted_virtual_key_does_not_reach_the_durable_audit_line(
    tmp_path: Path,
) -> None:
    """A real minted virtual key is gone from the persisted JSONL record."""
    token = _mint_real_virtual_key()
    path = tmp_path / "audit.jsonl"

    append_jsonl(path, json.dumps({"transcript": f"env dump: {token}"}))

    assert token not in path.read_text(encoding="utf-8")


def test_minted_virtual_key_line_stays_parseable_json(tmp_path: Path) -> None:
    """Redacting mid-record must not corrupt the line events.py later reads."""
    token = _mint_real_virtual_key()
    path = tmp_path / "audit.jsonl"

    append_jsonl(path, json.dumps({"transcript": f"leaked {token}", "seq": 7}))

    assert json.loads(path.read_text(encoding="utf-8").strip())["seq"] == 7


def test_published_key_id_survives_the_durable_audit_write(tmp_path: Path) -> None:
    """ADR-0138 publishes ``key_id`` on purpose; the scrubber must not eat it."""
    token = _mint_real_virtual_key()
    key_id = token.removeprefix("hfgw_").split(".", maxsplit=1)[0]
    path = tmp_path / "audit.jsonl"

    append_jsonl(path, json.dumps({"key_id": key_id}))

    assert json.loads(path.read_text(encoding="utf-8").strip())["key_id"] == key_id


def test_bare_key_id_trips_no_secret_pattern() -> None:
    """The detector half of the same invariant, stated directly."""
    key_id = _mint_real_virtual_key().removeprefix("hfgw_").split(".", maxsplit=1)[0]

    assert scan_for_secrets(key_id) == []


def test_control_token_does_not_reach_the_durable_audit_line(tmp_path: Path) -> None:
    """A canonical-grammar control token is redacted on the same write path."""
    path = tmp_path / "audit.jsonl"

    append_jsonl(path, json.dumps({"transcript": f"exported {_CONTROL_TOKEN}"}))

    assert _CONTROL_TOKEN not in path.read_text(encoding="utf-8")


def test_control_token_env_assignment_does_not_reach_the_audit_line(
    tmp_path: Path,
) -> None:
    """The realistic leak shape — an unquoted env dump — is redacted too."""
    path = tmp_path / "audit.jsonl"
    legacy = "legacy-operator-token-0123456789ab"

    append_jsonl(
        path,
        json.dumps(
            {"transcript": f"child env: HYDRAFLOW_GATEWAY_CONTROL_TOKEN={legacy}"}
        ),
    )

    assert legacy not in path.read_text(encoding="utf-8")


def test_gateway_redaction_is_idempotent() -> None:
    """A second pass over an already-scrubbed record must be a no-op."""
    once = scrub_secrets(f"{_mint_real_virtual_key()} {_CONTROL_TOKEN}")

    assert scrub_secrets(once) == once
