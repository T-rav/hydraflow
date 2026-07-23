"""Tests for model_pricing.py."""

from __future__ import annotations

import json
import logging

import pytest

from model_pricing import ModelPricingTable, ModelRate, load_pricing


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
        with pytest.raises(AttributeError):
            rate.input_cost_per_million = 999  # type: ignore[misc]


class TestModelPricingTable:
    def _write_asset(self, tmp_path, data):
        path = tmp_path / "pricing.json"
        path.write_text(json.dumps(data))
        return path

    def test_load_and_get_rate_by_exact_id(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-sonnet-4-20250514": {
                        "input_cost_per_million": 3.0,
                        "output_cost_per_million": 15.0,
                        "aliases": ["sonnet"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        rate = table.get_rate("claude-sonnet-4-20250514")
        assert rate is not None
        assert rate.input_cost_per_million == 3.0
        assert rate.output_cost_per_million == 15.0
        assert rate.cache_write_cost_per_million == 0.0

    def test_get_rate_by_alias(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-opus-4-20250514": {
                        "input_cost_per_million": 15.0,
                        "output_cost_per_million": 75.0,
                        "aliases": ["opus", "claude-4-opus"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        rate = table.get_rate("opus")
        assert rate is not None
        assert rate.output_cost_per_million == 75.0

    def test_get_rate_case_insensitive(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-3-5-haiku-20241022": {
                        "input_cost_per_million": 0.8,
                        "output_cost_per_million": 4.0,
                        "aliases": ["haiku"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        assert table.get_rate("HAIKU") is not None
        assert table.get_rate("Haiku") is not None

    def test_get_rate_fuzzy_substring_match(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-sonnet-4-20250514": {
                        "input_cost_per_million": 3.0,
                        "output_cost_per_million": 15.0,
                        "aliases": ["sonnet"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        rate = table.get_rate("claude-sonnet-4-20250514-extended")
        assert rate is not None
        assert rate.input_cost_per_million == 3.0

    def test_get_rate_unknown_returns_none(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {},
            },
        )
        table = ModelPricingTable(path)
        assert table.get_rate("unknown-model") is None

    def test_estimate_cost_delegates_to_rate(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-sonnet-4-20250514": {
                        "input_cost_per_million": 3.0,
                        "output_cost_per_million": 15.0,
                        "aliases": ["sonnet"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        cost = table.estimate_cost("sonnet", input_tokens=1000, output_tokens=500)
        expected = (3.0 * 1000 + 15.0 * 500) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_estimate_cost_unknown_returns_none(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {},
            },
        )
        table = ModelPricingTable(path)
        assert (
            table.estimate_cost("unknown", input_tokens=100, output_tokens=50) is None
        )

    def test_missing_file_returns_none(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        table = ModelPricingTable(path)
        assert table.get_rate("anything") is None

    def test_corrupt_json_handled_gracefully(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json")
        table = ModelPricingTable(path)
        assert table.get_rate("anything") is None

    def test_skips_entry_missing_required_fields(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "incomplete": {"input_cost_per_million": 1.0},
                },
            },
        )
        table = ModelPricingTable(path)
        assert table.get_rate("incomplete") is None

    def test_lazy_loading(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "model-a": {
                        "input_cost_per_million": 1.0,
                        "output_cost_per_million": 2.0,
                    },
                },
            },
        )
        table = ModelPricingTable(path)
        assert not table._loaded
        table.get_rate("model-a")
        assert table._loaded


class TestLoadPricing:
    def test_returns_table_instance(self, tmp_path):
        path = tmp_path / "pricing.json"
        path.write_text(json.dumps({"schema_version": 1, "models": {}}))
        table = load_pricing(path)
        assert isinstance(table, ModelPricingTable)


class TestOpenAICompatBackendModelsPriced:
    """Drift guard (#9856): the OpenAI-compatible one-shot backends send these
    exact model ids (config: zai -> ``glm-5.2``, kimi -> ``kimi-k3``). Telemetry
    records the model string, so the shipped pricing table MUST resolve it —
    otherwise kimi/z.ai bg-worker cost silently records as $0 next to the tracked
    Claude spend. When a backend model id is bumped, add the new id to
    src/assets/model_pricing.json AND to this list.
    """

    # (model_id, min tokens rate must be > 0)
    _BACKEND_MODEL_IDS = ["glm-5.2", "kimi-k3"]

    @pytest.mark.parametrize("model", _BACKEND_MODEL_IDS)
    def test_backend_model_is_priced_in_shipped_table(self, model: str) -> None:
        # load_pricing() with no path loads the real src/assets/model_pricing.json.
        pricing = load_pricing()
        cost = pricing.estimate_cost(model, input_tokens=1000, output_tokens=1000)
        assert cost is not None and cost > 0, (
            f"{model!r} is not priced in the shipped table — kimi/z.ai bg-worker "
            "cost telemetry will record $0. Add it to "
            "src/assets/model_pricing.json (#9856)."
        )

    def test_provider_prefixed_alias_resolves(self) -> None:
        # The telemetry model string is bare ``glm-5.2``, but the provider-form
        # ``zai/glm-5.2`` must resolve too (alias), for robustness.
        pricing = load_pricing()
        assert pricing.get_rate("zai/glm-5.2") is not None


class TestFuzzyFallbackGate:
    """#9466: the fuzzy fallback must not silently mis-rate unknown model ids.

    Tightened contract (resolution order unchanged: exact id -> alias -> fuzzy):

    * only multi-token candidates (canonical ids or aliases containing a
      delimiter) are fuzzy-eligible — bare tier aliases like ``opus`` never
      fuzzy-match;
    * a candidate must occur aligned on token boundaries, not inside a larger
      token;
    * a numeric token immediately after the match means a newer/different
      version — the lookup returns ``None`` instead of a stale tier price;
    * a fuzzy hit and an unknown model each emit a one-time observable log.
    """

    def _table(self, tmp_path, models):
        path = tmp_path / "pricing.json"
        path.write_text(json.dumps({"schema_version": 1, "models": models}))
        return ModelPricingTable(path)

    def _opus_models(self):
        return {
            "claude-opus-4-7": {
                "input_cost_per_million": 5.0,
                "output_cost_per_million": 25.0,
                "aliases": ["opus", "claude-opus-4-7"],
            },
            "claude-opus-4-20250514": {
                "input_cost_per_million": 15.0,
                "output_cost_per_million": 75.0,
                "aliases": ["claude-4-opus", "claude-opus-4"],
            },
        }

    def test_bare_tier_alias_never_fuzzy_matches_unknown_id(self, tmp_path):
        # Old behavior: "opus" in "claude-opus-4-9" -> claude-opus-4-7 rate.
        table = self._table(tmp_path, self._opus_models())
        assert table.get_rate("claude-opus-4-9") is None

    def test_numeric_version_residual_rejects_multi_token_alias(self, tmp_path):
        # "claude-opus-4" is a legit alias of the 4.0 entry, but a trailing
        # numeric token ("-9") marks a newer version — must not inherit it.
        table = self._table(tmp_path, self._opus_models())
        assert table.estimate_cost("claude-opus-4-9", 1000, 1000) is None

    def test_bare_tier_alias_still_resolves_exactly(self, tmp_path):
        table = self._table(tmp_path, self._opus_models())
        rate = table.get_rate("opus")
        assert rate is not None
        assert rate.input_cost_per_million == 5.0

    def test_non_numeric_suffix_variant_still_fuzzy_matches(self, tmp_path):
        # Variant tags after a full known id remain resolvable (canonical id
        # is a token-boundary prefix, residual token is non-numeric).
        table = self._table(tmp_path, self._opus_models())
        rate = table.get_rate("claude-opus-4-7-extended")
        assert rate is not None
        assert rate.input_cost_per_million == 5.0

    def test_provider_prefix_form_fuzzy_matches_on_token_boundary(self, tmp_path):
        table = self._table(tmp_path, self._opus_models())
        rate = table.get_rate("anthropic/claude-opus-4-7")
        assert rate is not None
        assert rate.input_cost_per_million == 5.0

    def test_candidate_inside_larger_token_does_not_match(self, tmp_path):
        # "claude-opus-4-7" appears in the string but glued to an alnum char
        # on the left — not a token-boundary match.
        table = self._table(tmp_path, self._opus_models())
        assert table.get_rate("xclaude-opus-4-7") is None

    def test_longest_candidate_wins(self, tmp_path):
        # Both "claude-opus-4" (alias) and "claude-opus-4-20250514"
        # (canonical) align at token boundaries; the more specific canonical
        # id must win.
        table = self._table(tmp_path, self._opus_models())
        rate = table.get_rate("claude-opus-4-20250514-preview")
        assert rate is not None
        assert rate.input_cost_per_million == 15.0

    def test_unknown_model_warns_once(self, tmp_path, caplog):
        table = self._table(tmp_path, self._opus_models())
        with caplog.at_level(logging.WARNING, logger="hydraflow.model_pricing"):
            assert table.get_rate("claude-opus-4-9") is None
            assert table.get_rate("claude-opus-4-9") is None
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "claude-opus-4-9" in r.getMessage()
        ]
        assert len(warnings) == 1

    def test_fuzzy_hit_logs_observable_signal_once(self, tmp_path, caplog):
        table = self._table(tmp_path, self._opus_models())
        with caplog.at_level(logging.INFO, logger="hydraflow.model_pricing"):
            assert table.get_rate("anthropic/claude-opus-4-7") is not None
            assert table.get_rate("anthropic/claude-opus-4-7") is not None
        signals = [
            r
            for r in caplog.records
            if "fuzzy" in r.getMessage().lower()
            and "anthropic/claude-opus-4-7" in r.getMessage()
        ]
        assert len(signals) == 1
