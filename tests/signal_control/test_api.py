import signal_control as sc


def test_public_api_surface():
    for name in (
        "Ewma",
        "SchmittHysteresis",
        "Persistence",
        "Cusum",
        "AdaptiveThreshold",
        "Corroborator",
        "AimdController",
        "PidController",
        "RetryController",
        "RetryOutcome",
        "RetryResult",
        "RetryStatus",
        "CircuitBreaker",
        "HistoricSignalStore",
    ):
        assert hasattr(sc, name), f"signal_control is missing {name}"
