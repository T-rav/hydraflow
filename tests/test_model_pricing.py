"""Tests for model_pricing.py."""

from __future__ import annotations

import json
import logging
from pathlib import Path

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
    _BACKEND_MODEL_IDS = ["glm-5.2", "glm-5.3", "kimi-k3"]

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


class TestInputIncludesCacheOverride:
    """Cache-inclusiveness is a property of the usage SHAPE, not the model id.

    The table flag describes the backend's one-shot OpenAI-compat face
    (``prompt_tokens`` includes cache). The same model served through the
    gateway arrives Anthropic-shaped (``input_tokens`` excludes cache), so the
    caller must be able to override the default per call, and the rate must
    never subtract when the counts are impossible under inclusive semantics.
    """

    def _inclusive_rate(self) -> ModelRate:
        return ModelRate(
            input_cost_per_million=1.4,
            output_cost_per_million=4.4,
            cache_write_cost_per_million=1.4,
            cache_read_cost_per_million=0.26,
            input_includes_cache=True,
        )

    def _exclusive_rate(self) -> ModelRate:
        return ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=3.75,
            cache_read_cost_per_million=0.30,
        )

    def test_table_default_inclusive_subtracts_plausible_cache(self) -> None:
        cost = self._inclusive_rate().estimate_cost(10_000, 0, cache_read_tokens=4_000)
        assert cost == pytest.approx((1.4 * 6_000 + 0.26 * 4_000) / 1e6)

    def test_override_false_bills_input_as_is_on_inclusive_rate(self) -> None:
        cost = self._inclusive_rate().estimate_cost(
            10_000, 0, cache_read_tokens=4_000, input_includes_cache=False
        )
        assert cost == pytest.approx((1.4 * 10_000 + 0.26 * 4_000) / 1e6)

    def test_override_true_subtracts_on_exclusive_rate(self) -> None:
        cost = self._exclusive_rate().estimate_cost(
            10_000, 0, cache_read_tokens=4_000, input_includes_cache=True
        )
        assert cost == pytest.approx((3.0 * 6_000 + 0.30 * 4_000) / 1e6)

    def test_override_none_keeps_table_default(self) -> None:
        rate = self._inclusive_rate()
        assert rate.estimate_cost(
            10_000, 0, cache_read_tokens=4_000, input_includes_cache=None
        ) == rate.estimate_cost(10_000, 0, cache_read_tokens=4_000)

    def test_impossible_inclusive_counts_bill_exclusive_and_log_debug(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # input < cache_read + cache_write cannot happen when input includes
        # the cache: the stream is exclusive-shaped, whatever the table says.
        with caplog.at_level(logging.DEBUG, logger="hydraflow.model_pricing"):
            cost = self._inclusive_rate().estimate_cost(
                1_244, 0, cache_read_tokens=46_784
            )
        assert cost == pytest.approx((1.4 * 1_244 + 0.26 * 46_784) / 1e6)
        assert any("exclusive" in record.getMessage() for record in caplog.records)

    def test_guard_counts_cache_write_tokens_too(self) -> None:
        cost = self._inclusive_rate().estimate_cost(
            5_000, 0, cache_write_tokens=3_000, cache_read_tokens=3_000
        )
        assert cost == pytest.approx((1.4 * 5_000 + 1.4 * 3_000 + 0.26 * 3_000) / 1e6)

    def test_override_true_with_impossible_counts_also_bills_exclusive(self) -> None:
        cost = self._exclusive_rate().estimate_cost(
            1_000, 0, cache_read_tokens=4_000, input_includes_cache=True
        )
        assert cost == pytest.approx((3.0 * 1_000 + 0.30 * 4_000) / 1e6)

    def test_table_estimate_passes_override_through(self, tmp_path) -> None:
        path = tmp_path / "pricing.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "models": {
                        "glm-x": {
                            "input_cost_per_million": 1.0,
                            "output_cost_per_million": 2.0,
                            "cache_read_cost_per_million": 0.1,
                            "input_includes_cache": True,
                        }
                    },
                }
            )
        )
        table = ModelPricingTable(path)

        inclusive = table.estimate_cost("glm-x", 10_000, 0, cache_read_tokens=4_000)
        exclusive = table.estimate_cost(
            "glm-x", 10_000, 0, cache_read_tokens=4_000, input_includes_cache=False
        )

        assert inclusive == pytest.approx((1.0 * 6_000 + 0.1 * 4_000) / 1e6)
        assert exclusive == pytest.approx((1.0 * 10_000 + 0.1 * 4_000) / 1e6)


class TestServedAndConfiguredModelsPriced:
    """Every model the factory can REQUEST and every model an upstream was
    observed to SERVE must resolve in the shipped table. 310/310 live gateway
    rows were ``cost_unknown`` because z.ai served ``glm-5.3`` for a
    ``glm-5.2`` request and only the requested id was priced.
    """

    _EVIDENCE = (
        Path(__file__).parent
        / "fixtures"
        / "gateway"
        / "live_provider_probe_evidence.json"
    )

    @classmethod
    def _model_ids(cls, value: object) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key in {"model_served", "model_requested"}
                    and isinstance(item, str)
                    and item
                ):
                    found.add(item)
                found |= cls._model_ids(item)
        elif isinstance(value, list):
            for item in value:
                found |= cls._model_ids(item)
        return found

    def test_live_probe_evidence_models_are_priced(self) -> None:
        model_ids = self._model_ids(json.loads(self._EVIDENCE.read_text()))
        assert {"glm-5.2", "glm-5.3"} <= model_ids, "fixture shape changed"

        pricing = load_pricing()
        unpriced = sorted(m for m in model_ids if pricing.get_rate(m) is None)

        assert unpriced == [], (
            f"served/requested models without a pricing entry: {unpriced}; "
            "add them to src/assets/model_pricing.json"
        )

    def test_every_configurable_model_default_is_priced(self) -> None:
        from config import HydraFlowConfig

        defaults = {
            name: field.default
            for name, field in HydraFlowConfig.model_fields.items()
            if name == "model" or name.endswith("_model")
        }
        assert len(defaults) >= 10, "model-field sweep found too few fields"

        pricing = load_pricing()
        unpriced = sorted(
            f"{name}={default!r}"
            for name, default in defaults.items()
            if isinstance(default, str)
            and default.strip()
            and pricing.get_rate(default) is None
        )

        assert unpriced == [], f"config model defaults without pricing: {unpriced}"

    def test_glm_5_3_matches_published_zai_rate(self) -> None:
        # https://docs.z.ai/guides/overview/pricing — GLM-5.3: $1.40/M input,
        # $4.40/M output, $0.26/M cached input (identical to GLM-5.2).
        pricing = load_pricing()
        rate = pricing.get_rate("glm-5.3")

        assert rate is not None
        assert (
            rate.input_cost_per_million,
            rate.output_cost_per_million,
            rate.cache_read_cost_per_million,
        ) == (1.4, 4.4, 0.26)
        # The table flag describes the one-shot OpenAI-compat face; the
        # gateway overrides it per call because its streams are Anthropic-shaped.
        assert rate.input_includes_cache is True
        assert pricing.get_rate("zai/glm-5.3") == rate
        assert pricing.get_rate("glm-5.2") == rate
