from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _compose() -> dict:
    return yaml.safe_load((_ROOT / "docker-compose.sandbox.yml").read_text())


def test_sandbox_places_fake_provider_credential_only_in_gateway() -> None:
    services = _compose()["services"]
    assert {"fake-llm-http", "gateway", "hydraflow", "playwright"} <= services.keys()

    gateway_env = services["gateway"]["environment"]
    hydraflow_env = services["hydraflow"]["environment"]
    playwright_env = services["playwright"]["environment"]

    assert gateway_env["GATEWAY_ANTHROPIC_API_KEY"] == "sandbox-provider-key"
    assert "ANTHROPIC_API_KEY" not in hydraflow_env
    assert "ANTHROPIC_AUTH_TOKEN" not in hydraflow_env
    assert "GATEWAY_ANTHROPIC_API_KEY" not in hydraflow_env
    assert "GATEWAY_ANTHROPIC_API_KEY" not in playwright_env


def test_sandbox_shares_metadata_read_only_but_never_body_store() -> None:
    services = _compose()["services"]
    gateway_volumes = services["gateway"]["volumes"]
    hydraflow_volumes = services["hydraflow"]["volumes"]

    assert "gateway-metadata:/var/lib/hydraflow-gateway/metadata" in gateway_volumes
    assert "gateway-metadata:/gateway-metadata:ro" in hydraflow_volumes
    assert services["hydraflow"]["environment"]["HYDRAFLOW_GATEWAY_LEDGER_PATH"] == (
        "/gateway-metadata/requests.jsonl"
    )
    assert "gateway-bodies:/var/lib/hydraflow-gateway/bodies" in gateway_volumes
    assert not any("gateway-bodies" in volume for volume in hydraflow_volumes)


def test_hydraflow_boot_waits_for_healthy_gateway_and_fake_upstream() -> None:
    services = _compose()["services"]
    assert services["gateway"]["depends_on"]["fake-llm-http"]["condition"] == (
        "service_healthy"
    )
    assert services["hydraflow"]["depends_on"]["gateway"]["condition"] == (
        "service_healthy"
    )
    assert (
        services["gateway"]["depends_on"]["gateway-storage-init"]["condition"]
        == "service_completed_successfully"
    )
    assert services["gateway-storage-init"]["user"] == "0:0"
    init_command = services["gateway-storage-init"]["command"][0]
    assert "os.chmod(metadata,0o750)" in init_command
    assert "os.chmod(bodies,0o700)" in init_command
    assert services["gateway"].get("user") != "0:0"


def test_sandbox_gateway_accepts_a_default_agent_timeout_lease() -> None:
    services = _compose()["services"]
    gateway_max_ttl = int(
        services["gateway"]["environment"]["GATEWAY_MAX_KEY_TTL_SECONDS"]
    )
    requested_ttl = int(
        services["hydraflow"]["environment"]["HYDRAFLOW_GATEWAY_KEY_TTL_SECONDS"]
    )

    assert requested_ttl >= 3600 + 60
    assert gateway_max_ttl >= requested_ttl


def test_gateway_scenario_initializes_an_observed_empty_direct_source() -> None:
    """s91 proves its zero bypass denominator instead of assuming absence."""
    from tests.sandbox_scenarios.scenarios.s91_gateway_session_tap import seed

    scenario_seed = seed()

    assert scenario_seed.prompt_telemetry_source_initialized is True
