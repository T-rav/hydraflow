"""Config surface and CH-1 registration for the artifact chain (ADR-0149)."""

from audit_chain import AuditStreamSpec, audit_streams
from config import HydraFlowConfig
from tests.helpers import ConfigFactory


def _spec(config: HydraFlowConfig, name: str) -> AuditStreamSpec:
    """Return the named stream from *config*'s registry.

    Takes the config rather than building one: ConfigFactory.create() mints
    a fresh temp repo root per call, so two calls produce paths that can
    never compare equal.
    """
    return next(s for s in audit_streams(config) if s.name == name)


def test_change_chain_stream_is_registered():
    names = {spec.name for spec in audit_streams(ConfigFactory.create())}

    assert "change_chain" in names


def test_change_chain_stream_keeps_records_forever_by_default():
    config = ConfigFactory.create()

    assert _spec(config, "change_chain").retention_days is None


def test_change_chain_stream_reads_the_recorded_at_timestamp_key():
    config = ConfigFactory.create()

    assert _spec(config, "change_chain").timestamp_key == "recorded_at"


def test_change_chain_stream_lives_beside_the_other_repo_scoped_chains():
    config = ConfigFactory.create()

    assert (
        _spec(config, "change_chain").path.parent == config.approval_records_path.parent
    )


def test_change_chain_is_enabled_by_default():
    assert ConfigFactory.create().change_chain_enabled is True


def test_change_chain_can_be_disabled():
    config = ConfigFactory.create().model_copy(update={"change_chain_enabled": False})

    assert config.change_chain_enabled is False


def test_change_chain_path_is_a_runtime_stream_not_committed_content():
    config = ConfigFactory.create()

    assert config.data_root in config.change_chain_path.parents
