"""Tests for model_pricing.py."""

from __future__ import annotations

from model_pricing import ModelPricingTable, ModelRate, load_pricing


class _InMemoryPricingState:
    """Minimal in-memory state for model pricing tests."""

    def __init__(self):
        self._pricing: list[dict] = []

    def load_all_model_pricing(self) -> list[dict]:
        return self._pricing


def _make_table(models: dict) -> ModelPricingTable:
    """Create a ModelPricingTable backed by an in-memory state.

    *models* uses the same format as the old JSON file:
    ``{model_id: {input_cost_per_million: ..., output_cost_per_million: ..., aliases: [...]}}``
    """
    state = _InMemoryPricingState()
    for model_id, fields in models.items():
        row = {
            "model_id": model_id,
            "input_cost_per_million": fields.get("input_cost_per_million", 0),
            "output_cost_per_million": fields.get("output_cost_per_million", 0),
            "cache_write_cost_per_million": fields.get(
                "cache_write_cost_per_million", 0
            ),
            "cache_read_cost_per_million": fields.get("cache_read_cost_per_million", 0),
            "aliases": fields.get("aliases", []),
        }
        state._pricing.append(row)
    return ModelPricingTable(state=state)


class TestModelRate:
    def test_estimate_cost_input_only(self):
        rate = ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=0.0,
            cache_read_cost_per_million=0.0,
        )
        cost = rate.estimate_cost(input_tokens=1_000_000, output_tokens=0)
        assert cost == 3.0

    def test_estimate_cost_output_only(self):
        rate = ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=0.0,
            cache_read_cost_per_million=0.0,
        )
        cost = rate.estimate_cost(input_tokens=0, output_tokens=1_000_000)
        assert cost == 15.0

    def test_estimate_cost_with_cache(self):
        rate = ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=3.75,
            cache_read_cost_per_million=0.30,
        )
        cost = rate.estimate_cost(
            input_tokens=500_000,
            output_tokens=100_000,
            cache_write_tokens=200_000,
            cache_read_tokens=300_000,
        )
        expected = (
            3.0 * 500_000 + 15.0 * 100_000 + 3.75 * 200_000 + 0.30 * 300_000
        ) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_frozen_dataclass(self):
        rate = ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=0.0,
            cache_read_cost_per_million=0.0,
        )
        try:
            rate.input_cost_per_million = 999  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestModelPricingTable:
    def test_load_and_get_rate_by_exact_id(self):
        table = _make_table(
            {
                "claude-sonnet-4-20250514": {
                    "input_cost_per_million": 3.0,
                    "output_cost_per_million": 15.0,
                    "aliases": ["sonnet"],
                }
            }
        )
        rate = table.get_rate("claude-sonnet-4-20250514")
        assert rate is not None
        assert rate.input_cost_per_million == 3.0
        assert rate.output_cost_per_million == 15.0
        assert rate.cache_write_cost_per_million == 0.0

    def test_get_rate_by_alias(self):
        table = _make_table(
            {
                "claude-opus-4-20250514": {
                    "input_cost_per_million": 15.0,
                    "output_cost_per_million": 75.0,
                    "aliases": ["opus", "claude-4-opus"],
                }
            }
        )
        rate = table.get_rate("opus")
        assert rate is not None
        assert rate.output_cost_per_million == 75.0

    def test_get_rate_case_insensitive(self):
        table = _make_table(
            {
                "claude-3-5-haiku-20241022": {
                    "input_cost_per_million": 0.8,
                    "output_cost_per_million": 4.0,
                    "aliases": ["haiku"],
                }
            }
        )
        assert table.get_rate("HAIKU") is not None
        assert table.get_rate("Haiku") is not None

    def test_get_rate_fuzzy_substring_match(self):
        table = _make_table(
            {
                "claude-sonnet-4-20250514": {
                    "input_cost_per_million": 3.0,
                    "output_cost_per_million": 15.0,
                    "aliases": ["sonnet"],
                }
            }
        )
        rate = table.get_rate("claude-sonnet-4-20250514-extended")
        assert rate is not None
        assert rate.input_cost_per_million == 3.0

    def test_get_rate_unknown_returns_none(self):
        table = _make_table({})
        assert table.get_rate("unknown-model") is None

    def test_estimate_cost_delegates_to_rate(self):
        table = _make_table(
            {
                "claude-sonnet-4-20250514": {
                    "input_cost_per_million": 3.0,
                    "output_cost_per_million": 15.0,
                    "aliases": ["sonnet"],
                }
            }
        )
        cost = table.estimate_cost("sonnet", input_tokens=1000, output_tokens=500)
        expected = (3.0 * 1000 + 15.0 * 500) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_estimate_cost_unknown_returns_none(self):
        table = _make_table({})
        assert (
            table.estimate_cost("unknown", input_tokens=100, output_tokens=50) is None
        )

    def test_no_state_returns_none(self):
        table = ModelPricingTable()
        assert table.get_rate("anything") is None

    def test_empty_state_returns_none(self):
        table = _make_table({})
        assert table.get_rate("anything") is None

    def test_skips_entry_missing_required_fields(self):
        table = _make_table(
            {
                "incomplete": {"input_cost_per_million": 1.0},
            }
        )
        # Should still load since output_cost defaults to 0
        rate = table.get_rate("incomplete")
        assert rate is not None
        assert rate.input_cost_per_million == 1.0
        assert rate.output_cost_per_million == 0.0

    def test_lazy_loading(self):
        table = _make_table(
            {
                "model-a": {
                    "input_cost_per_million": 1.0,
                    "output_cost_per_million": 2.0,
                },
            }
        )
        assert not table._loaded
        table.get_rate("model-a")
        assert table._loaded


class TestLoadPricing:
    def test_returns_table_instance(self):
        table = load_pricing()
        assert isinstance(table, ModelPricingTable)
