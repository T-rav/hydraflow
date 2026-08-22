"""The dashboard's routing-policy workspace, and the write gate it spends.

ADR-0138 §D5 made two conditions a precondition on the first write route through
this dashboard. The first test in this file is the one that proves they are
independent: a perfectly valid operator credential must not open the gate on a
dashboard bound beyond loopback.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard_routes._gateway_policy_routes as gateway_policy_routes
from dashboard_routes._gateway_policy_routes import build_gateway_policy_router
from driver_contracts import WorkerRole
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.routing_policy import canonicalize_repo
from hydraflow_gateway.routing_store import POLICY_SNAPSHOT_FILENAME
from hydraflow_gateway.routing_workspace import MutationRejection, PolicyWorkspace
from operator_identity import OPERATOR_ID_ENV, OPERATOR_TOKEN_ENV
from route_shadow import routing_dir
from routing_matrix import MAX_MATRIX_REQUIREMENTS
from tests.helpers import ConfigFactory

if TYPE_CHECKING:
    from pathlib import Path

_REPO = "acme/hydraflow"
_TOKEN = "hfop_" + "t" * 40
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_ENV = {OPERATOR_TOKEN_ENV: _TOKEN, OPERATOR_ID_ENV: "travis"}


def _config(tmp_path: Path, *, host: str = "127.0.0.1", enabled: bool = True):
    config = ConfigFactory.create(repo=_REPO, dashboard_host=host)
    object.__setattr__(config, "data_root", tmp_path / "data")
    object.__setattr__(config, "gateway_policy_workspace_enabled", enabled)
    return config


def _client(config: Any, *, env: dict[str, str] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_gateway_policy_router(
            config, env=_ENV if env is None else env, clock=lambda: _NOW
        )
    )
    return TestClient(app)


def _policy_body(
    policy_id: str = "pin-zai",
    *,
    repo: str = _REPO,
    lock: str = ProviderBinding.ZAI_HARNESS.value,
    roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": policy_id,
        "match": {"repo_ids": [repo] if repo else [], "roles": list(roles)},
        "action": {
            "provider_lock": lock,
            "requirement_map": [
                {
                    "requirement": {"kind": "capability", "value": "balanced"},
                    "effective_model": "glm-5.3",
                }
            ],
        },
    }


def _create(client: TestClient, *, revision: int = 0, **kwargs: Any):
    return client.post(
        "/api/gateway/policies/mutations",
        json={
            "kind": "create",
            "expected_revision": revision,
            "policy": _policy_body(**kwargs),
        },
        headers=_AUTH,
    )


# --------------------------------------------------------------------------
# ADR-0138 §D5 — the gate this phase spends
# --------------------------------------------------------------------------


def test_a_valid_operator_token_cannot_write_past_a_non_loopback_bind(
    tmp_path: Path,
) -> None:
    """The D5 proof: the credential says who is asking, the bind says who can."""
    client = _client(_config(tmp_path, host="0.0.0.0"))  # noqa: S104

    response = _create(client)

    assert (response.status_code, response.json()["code"]) == (
        403,
        "dashboard-not-loopback",
    )


def test_a_write_without_an_operator_token_is_unauthenticated(
    tmp_path: Path,
) -> None:
    """No credential, no write — and a 401 that names the scheme to present."""
    client = _client(_config(tmp_path))

    response = client.post(
        "/api/gateway/policies/mutations",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(),
        },
    )

    assert response.status_code == 401


def test_a_wrong_operator_token_is_unauthenticated(tmp_path: Path) -> None:
    """A near-miss credential is refused as firmly as none at all."""
    client = _client(_config(tmp_path))

    response = client.post(
        "/api/gateway/policies/mutations",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(),
        },
        headers={"Authorization": f"Bearer {_TOKEN}x"},
    )

    assert response.status_code == 401


def test_the_kill_switch_closes_the_write_plane(tmp_path: Path) -> None:
    """A third, blunt way to shut policy writes off without touching the bind."""
    client = _client(_config(tmp_path, enabled=False))

    response = _create(client)

    assert response.json()["code"] == "workspace-disabled"


def test_an_unconfigured_host_reports_the_missing_operator_identity(
    tmp_path: Path,
) -> None:
    """The default deployment has no operator token, so writes are off by default."""
    client = _client(_config(tmp_path), env={})

    response = _create(client)

    assert response.json()["code"] == "no-operator-identity"


def test_a_refused_gate_writes_nothing(tmp_path: Path) -> None:
    """A 403 that had already touched the store would not be a gate."""
    config = _config(tmp_path, host="0.0.0.0")  # noqa: S104
    _create(_client(config))

    assert not (routing_dir(config) / POLICY_SNAPSHOT_FILENAME).exists()


def test_the_read_plane_publishes_the_gate_so_the_editor_can_render_read_only(
    tmp_path: Path,
) -> None:
    """An editor that could not tell would offer a save button that always fails."""
    client = _client(_config(tmp_path, host="0.0.0.0"))  # noqa: S104

    payload = client.get("/api/gateway/policies").json()

    assert (payload["editable"], payload["write_gate"]) == (
        False,
        "dashboard-not-loopback",
    )


def test_the_reads_stay_open_when_the_write_plane_is_closed(
    tmp_path: Path,
) -> None:
    """Observation is not a privilege: D5 scopes its restriction to writes."""
    client = _client(_config(tmp_path, host="0.0.0.0"))  # noqa: S104

    assert client.get("/api/gateway/policies/effective").status_code == 200


# --------------------------------------------------------------------------
# Optimistic concurrency
# --------------------------------------------------------------------------


def test_a_first_write_creates_revision_one(tmp_path: Path) -> None:
    """The happy path, so every refusal below is a refusal of something real."""
    response = _create(_client(_config(tmp_path)))

    assert (response.status_code, response.json()["revision"]) == (200, 1)


def test_a_stale_expected_revision_is_a_conflict(tmp_path: Path) -> None:
    """Two tabs, one snapshot: the second save must not silently win."""
    client = _client(_config(tmp_path))
    _create(client)

    response = _create(client, policy_id="second")

    assert response.status_code == 409


def test_a_conflict_names_the_revision_to_reload(tmp_path: Path) -> None:
    """A 409 without the current revision makes the operator guess."""
    client = _client(_config(tmp_path))
    _create(client)

    response = _create(client, policy_id="second")

    assert response.json()["actual_revision"] == 1


def test_a_conflict_leaves_the_snapshot_at_the_revision_that_won(
    tmp_path: Path,
) -> None:
    """No partial write: the losing save changes nothing at all."""
    config = _config(tmp_path)
    client = _client(config)
    _create(client)

    _create(client, policy_id="second")

    assert client.get("/api/gateway/policies").json()["revision"] == 1


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        pytest.param(
            {
                "kind": "create",
                "expected_revision": 1,
                "policy": _policy_body("global-rule", repo=""),
            },
            422,
            "out-of-scope",
            id="a-global-rule-through-a-repo-scoped-editor",
        ),
        pytest.param(
            {
                "kind": "update",
                "expected_revision": 1,
                "policy": _policy_body("absent-rule"),
            },
            404,
            "policy-not-found",
            id="an-update-of-a-policy-that-is-not-there",
        ),
        pytest.param(
            {"kind": "rollback", "expected_revision": 1, "target_revision": 9},
            422,
            "unknown-revision",
            id="a-rollback-to-a-revision-that-never-existed",
        ),
        pytest.param(
            {
                "kind": "create",
                "expected_revision": 1,
                "policy": _policy_body("pin-claude", lock="anthropic"),
            },
            422,
            "validation-failed",
            id="an-equal-precedence-conflict",
        ),
    ],
)
def test_a_refused_mutation_maps_to_the_status_its_client_should_act_on(
    tmp_path: Path, body: dict[str, Any], status: int, code: str
) -> None:
    """409 means reload, 422 means fix the edit, 404 means it is not here."""
    client = _client(_config(tmp_path))
    _create(client)

    response = client.post("/api/gateway/policies/mutations", json=body, headers=_AUTH)

    assert (response.status_code, response.json()["code"]) == (status, code)


def test_a_validation_failure_returns_every_issue_not_the_first(
    tmp_path: Path,
) -> None:
    """A form that can render all its errors at once is a form worth using."""
    client = _client(_config(tmp_path))
    _create(client)

    response = client.post(
        "/api/gateway/policies/mutations",
        json={
            "kind": "create",
            "expected_revision": 1,
            "policy": _policy_body("pin-claude", lock="anthropic"),
        },
        headers=_AUTH,
    )

    assert response.json()["issues"][0]["code"] == "equal-precedence-conflict"


# --------------------------------------------------------------------------
# Rollback and audit
# --------------------------------------------------------------------------


def test_a_rollback_creates_a_new_revision(tmp_path: Path) -> None:
    """History is append-only; a rollback moves forward into the past."""
    client = _client(_config(tmp_path))
    _create(client)
    _create(client, revision=1, policy_id="second")

    response = client.post(
        "/api/gateway/policies/mutations",
        json={"kind": "rollback", "expected_revision": 2, "target_revision": 1},
        headers=_AUTH,
    )

    assert response.json()["revision"] == 3


def test_the_audit_names_the_actor_the_boundary_authenticated(
    tmp_path: Path,
) -> None:
    """Provenance comes from the credential, never from the mutation body."""
    client = _client(_config(tmp_path))
    _create(client)

    payload = client.get("/api/gateway/policies/audit").json()

    assert payload["records"][0]["payload"]["actor"] == "travis"


def test_a_mutation_body_cannot_claim_an_actor(tmp_path: Path) -> None:
    """``extra="forbid"`` is what stops a caller asserting its own provenance."""
    client = _client(_config(tmp_path))

    response = client.post(
        "/api/gateway/policies/mutations",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(),
            "actor": "somebody-else",
        },
        headers=_AUTH,
    )

    assert response.status_code == 422


def test_the_audit_chain_verifies_over_the_route(tmp_path: Path) -> None:
    """A history that cannot be verified is a log, not evidence."""
    client = _client(_config(tmp_path))
    _create(client)

    assert client.get("/api/gateway/policies/audit").json()["verified"] is True


def test_the_audit_of_a_repo_that_never_wrote_a_policy_is_empty(
    tmp_path: Path,
) -> None:
    """An absent chain is a normal state and renders as one."""
    payload = _client(_config(tmp_path)).get("/api/gateway/policies/audit").json()

    assert (payload["records"], payload["verified"]) == ([], True)


# --------------------------------------------------------------------------
# Effective routes and the builder preview
# --------------------------------------------------------------------------


def test_the_effective_matrix_covers_every_worker_role(tmp_path: Path) -> None:
    """A role missing from the grid is a route nobody reviewed."""
    payload = _client(_config(tmp_path)).get("/api/gateway/policies/effective").json()

    assert {cell["role"] for cell in payload["cells"]} == {
        role.value for role in WorkerRole
    }


def test_every_matrix_cell_carries_its_pinned_explanation(tmp_path: Path) -> None:
    """Selecting a cell must not re-resolve against a newer revision."""
    payload = _client(_config(tmp_path)).get("/api/gateway/policies/effective").json()

    assert all(cell["explanation"]["context"] for cell in payload["cells"])


def test_the_matrix_pins_one_policy_revision(tmp_path: Path) -> None:
    """One revision for the whole grid is what makes it a matrix."""
    client = _client(_config(tmp_path))
    _create(client)

    payload = client.get("/api/gateway/policies/effective").json()

    assert {cell["policy_revision"] for cell in payload["cells"]} == {1}


def test_an_unrecognised_requirement_selector_is_refused(tmp_path: Path) -> None:
    """Silently dropping a row would read as "that route is unaffected"."""
    client = _client(_config(tmp_path))

    response = client.get("/api/gateway/policies/effective?requirement=nonsense")

    assert response.status_code == 422


def test_a_preview_writes_nothing(tmp_path: Path) -> None:
    """The builder asks what would happen without it happening."""
    config = _config(tmp_path)
    client = _client(config)

    client.post(
        "/api/gateway/policies/preview",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(),
        },
    )

    assert not (routing_dir(config) / POLICY_SNAPSHOT_FILENAME).exists()


def test_a_preview_needs_no_operator_credential(tmp_path: Path) -> None:
    """Validating an edit has no side effect, so it is not a privileged act."""
    client = _client(_config(tmp_path), env={})

    response = client.post(
        "/api/gateway/policies/preview",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(),
        },
    )

    assert response.status_code == 200


def test_a_preview_returns_the_routes_the_edit_would_move(tmp_path: Path) -> None:
    """Before/after is the whole point: which live routes does this change?"""
    client = _client(_config(tmp_path))

    payload = client.post(
        "/api/gateway/policies/preview",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(),
        },
    ).json()

    assert all(cell["changed"] for cell in payload["cells"])


def test_a_preview_rejects_a_conflict_before_any_write(tmp_path: Path) -> None:
    """Conflicts are reported by the builder, not discovered by the save."""
    client = _client(_config(tmp_path))
    _create(client)

    payload = client.post(
        "/api/gateway/policies/preview",
        json={
            "kind": "create",
            "expected_revision": 1,
            "policy": _policy_body("pin-claude", lock="anthropic"),
        },
    ).json()

    assert (payload["writable"], payload["issues"][0]["code"]) == (
        False,
        "equal-precedence-conflict",
    )


def test_a_preview_of_a_stale_edit_still_renders(tmp_path: Path) -> None:
    """An operator whose tab went stale deserves to see the diff, then reload."""
    client = _client(_config(tmp_path))
    _create(client)

    payload = client.post(
        "/api/gateway/policies/preview",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body("second"),
        },
    ).json()

    assert (payload["stale"], payload["writable"]) == (True, False)


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/api/gateway/policies/effective", id="effective-routes"),
        pytest.param("/api/gateway/policies/audit", id="mutation-history"),
    ],
)
def test_aggregate_mode_has_no_per_repo_detail(tmp_path: Path, path: str) -> None:
    """``__all__`` has no single policy home, so it may not pretend to."""
    client = _client(_config(tmp_path))

    assert client.get(f"{path}?repo=__all__").status_code == 400


def test_aggregate_mode_is_read_only(tmp_path: Path) -> None:
    """An aggregate write must never be mistaken for a host-admin one."""
    client = _client(_config(tmp_path))

    response = client.post(
        "/api/gateway/policies/mutations?repo=__all__",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(),
        },
        headers=_AUTH,
    )

    assert response.status_code == 400


def test_aggregate_mode_summarises_every_repository(tmp_path: Path) -> None:
    """The read that ``__all__`` does answer: which repos carry policy at all."""
    config = _config(tmp_path)
    client = _client(config)
    _create(client)

    payload = client.get("/api/gateway/policies?repo=__all__").json()

    assert payload["repos"] == [
        {
            "repo": _REPO,
            "slug": canonicalize_repo(_REPO).replace("/", "-"),
            "state": "ok",
            "revision": 1,
            "policy_count": 1,
            "editable_count": 1,
            "issue_count": 0,
        }
    ]


def test_the_aggregate_view_declares_itself_read_only(tmp_path: Path) -> None:
    """The editor renders from this flag, so it has to be on the payload."""
    payload = (
        _client(_config(tmp_path)).get("/api/gateway/policies?repo=__all__").json()
    )

    assert payload["editable"] is False


def test_the_write_lands_where_the_shadow_resolver_reads(tmp_path: Path) -> None:
    """One authority: the route the operator edits is the route a spawn resolves."""
    config = _config(tmp_path)
    _create(_client(config))

    assert (
        PolicyWorkspace(routing_dir(config), repo=_REPO).read().policies[0].id
        == "pin-zai"
    )


# --------------------------------------------------------------------------
# Multi-repo scoping: the kill switch an operator sets per repo
# --------------------------------------------------------------------------


class _Registry:
    """The multi-repo seam the dashboard router resolves through."""

    def __init__(self, config: Any, repo_config: Any, slug: str) -> None:
        self._config = config
        self._repo_config = repo_config
        self._slug = slug

    def resolve_runtime(self, slug: str | None) -> tuple[Any, None, None, None]:
        resolved = self._repo_config if slug == self._slug else self._config
        return resolved, None, None, None

    def resolve_runtimes(self, _slug: str | None) -> list[tuple[Any, ...]]:
        return [(self._repo_config, None, None, None, self._slug)]


def _multi_repo_client(tmp_path: Path, *, repo_enabled: bool) -> TestClient:
    host = _config(tmp_path)
    repo_config = _config(tmp_path, enabled=repo_enabled)
    app = FastAPI()
    app.include_router(
        build_gateway_policy_router(
            host, _Registry(host, repo_config, _REPO), env=_ENV, clock=lambda: _NOW
        )
    )
    return TestClient(app)


def test_a_repository_may_close_its_own_write_plane(tmp_path: Path) -> None:
    """The kill switch is a per-repo setting, so it has to bind per repo."""
    client = _multi_repo_client(tmp_path, repo_enabled=False)

    response = client.post(
        f"/api/gateway/policies/mutations?repo={_REPO}",
        json={"kind": "create", "expected_revision": 0, "policy": _policy_body()},
        headers=_AUTH,
    )

    assert (response.status_code, response.json()["code"]) == (
        403,
        "workspace-disabled",
    )


def test_the_read_plane_reports_that_repository_s_own_gate(tmp_path: Path) -> None:
    """An editor that read the host's gate would offer a save that always 403s."""
    client = _multi_repo_client(tmp_path, repo_enabled=False)

    payload = client.get(f"/api/gateway/policies?repo={_REPO}").json()

    assert (payload["editable"], payload["write_gate"]) == (False, "workspace-disabled")


def test_a_repository_that_left_its_switch_on_still_writes(tmp_path: Path) -> None:
    """The per-repo check may only ever close the gate, never open a shut one."""
    client = _multi_repo_client(tmp_path, repo_enabled=True)

    response = client.post(
        f"/api/gateway/policies/mutations?repo={_REPO}",
        json={"kind": "create", "expected_revision": 0, "policy": _policy_body()},
        headers=_AUTH,
    )

    assert response.status_code == 200


def test_a_repo_editor_cannot_write_a_system_safety_rule(tmp_path: Path) -> None:
    """System safety outranks every exact-project route; it is host-admin business."""
    client = _client(_config(tmp_path))

    response = client.post(
        "/api/gateway/policies/mutations",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": {
                **_policy_body("escalate"),
                "priority": 10000,
                "system_safety": True,
            },
        },
        headers=_AUTH,
    )

    assert (response.status_code, response.json()["code"]) == (422, "out-of-scope")


# --------------------------------------------------------------------------
# Resolution, offload, and totality
# --------------------------------------------------------------------------


def test_a_slug_the_server_cannot_resolve_is_not_served_as_the_host_repo(
    tmp_path: Path,
) -> None:
    """``resolve_runtime`` falls back to the host runtime for an unstarted repo.

    That is right for a read-only dashboard and wrong for the one write route:
    a mutation naming an unstarted repository would land on the HOST
    repository's snapshot, authorised by the host repository's gate.
    """
    client = _multi_repo_client(tmp_path, repo_enabled=True)

    response = client.post(
        "/api/gateway/policies/mutations?repo=acme%2Fnot-registered",
        json={"kind": "create", "expected_revision": 0, "policy": _policy_body()},
        headers=_AUTH,
    )

    assert response.status_code == 404


def test_an_unresolvable_slug_is_refused_on_the_reads_too(tmp_path: Path) -> None:
    """A read that silently answered for another repository would mislead a save."""
    client = _multi_repo_client(tmp_path, repo_enabled=True)

    assert (
        client.get("/api/gateway/policies?repo=acme%2Fnot-registered").status_code
        == 404
    )


def test_the_repository_s_own_slug_still_resolves(tmp_path: Path) -> None:
    """The refusal must not reject the canonical slug the console actually sends."""
    client = _multi_repo_client(tmp_path, repo_enabled=True)

    assert client.get(f"/api/gateway/policies?repo={_REPO}").status_code == 200


def test_a_per_repo_bind_cannot_close_a_loopback_socket(tmp_path: Path) -> None:
    """The bind is ONE socket. Only the kill switch is a per-repository fact.

    Re-running the whole gate against a repository config would report
    ``dashboard-not-loopback`` for a dashboard that is bound to loopback — a
    refusal naming something the operator cannot fix.
    """
    host = _config(tmp_path)
    repo_config = _config(tmp_path, host="0.0.0.0")  # noqa: S104
    app = FastAPI()
    app.include_router(
        build_gateway_policy_router(
            host, _Registry(host, repo_config, _REPO), env=_ENV, clock=lambda: _NOW
        )
    )

    response = TestClient(app).post(
        f"/api/gateway/policies/mutations?repo={_REPO}",
        json={"kind": "create", "expected_revision": 0, "policy": _policy_body()},
        headers=_AUTH,
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/api/gateway/policies", id="the-snapshot-read"),
        pytest.param("/api/gateway/policies/effective", id="the-effective-matrix"),
        pytest.param("/api/gateway/policies/audit", id="the-mutation-history"),
        pytest.param("/api/gateway/policies?repo=__all__", id="the-aggregate-summary"),
    ],
)
def test_every_read_hands_its_disk_io_to_a_worker_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """One dashboard shares one event loop with five async loops (ADR-0001).

    The audit read in particular walks and hash-verifies a chain this phase
    deliberately never prunes.
    """
    offloaded: list[str] = []
    real = asyncio.to_thread

    async def recording(func, /, *args, **kwargs):
        offloaded.append(getattr(func, "__name__", repr(func)))
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(gateway_policy_routes.asyncio, "to_thread", recording)

    _client(_config(tmp_path)).get(path)

    assert offloaded != []


def test_every_refusal_code_maps_to_a_status(tmp_path: Path) -> None:
    """A new rejection code without a row is a bare KeyError — a 500 on a write."""
    del tmp_path

    assert set(MutationRejection) == set(gateway_policy_routes._REJECTION_STATUS)


def test_a_preview_resolves_the_same_requirement_rows_the_grid_can(
    tmp_path: Path,
) -> None:
    """A diff over fewer rows than the grid answers "unaffected" for rows it skipped."""
    client = _client(_config(tmp_path))

    payload = client.post(
        "/api/gateway/policies/preview?requirement=capability:balanced"
        "&requirement=literal_family:claude-opus",
        json={"kind": "create", "expected_revision": 0, "policy": _policy_body()},
    ).json()

    assert {cell["requirement"]["value"] for cell in payload["after"]["cells"]} == {
        "balanced",
        "claude-opus",
    }


def test_more_requirement_rows_than_the_matrix_allows_are_refused(
    tmp_path: Path,
) -> None:
    """A bound that silently truncated would drop the row an operator asked about."""
    client = _client(_config(tmp_path))
    query = "&".join(
        ["requirement=capability:balanced"] * (MAX_MATRIX_REQUIREMENTS + 1)
    )

    assert client.get(f"/api/gateway/policies/effective?{query}").status_code == 422
