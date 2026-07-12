"""Unit tests for the eval provider-override helper.

Deterministic (no model calls), so these run in the default suite — they pin the
mechanism that lets an eval corpus be A/B'd against a candidate LLM backend.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import HydraFlowConfig
from tests.evals._provider_override import (
    apply_provider_override,
    backend_label,
    eval_backend,
)

_PF = "wiki_compilation_provider"
_MF = "wiki_compilation_model"


class TestEvalBackend:
    def test_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_EVAL_PROVIDER", raising=False)
        monkeypatch.delenv("HYDRAFLOW_EVAL_MODEL", raising=False)
        assert eval_backend() == (None, None)

    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_EVAL_PROVIDER", "openrouter")
        monkeypatch.setenv("HYDRAFLOW_EVAL_MODEL", "deepseek/deepseek-chat")
        assert eval_backend() == ("openrouter", "deepseek/deepseek-chat")


class TestApplyOverride:
    def test_noop_when_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_EVAL_PROVIDER", raising=False)
        monkeypatch.delenv("HYDRAFLOW_EVAL_MODEL", raising=False)
        cfg = HydraFlowConfig()
        before = (cfg.wiki_compilation_provider, cfg.wiki_compilation_model)
        apply_provider_override(cfg, provider_field=_PF, model_field=_MF)
        assert (cfg.wiki_compilation_provider, cfg.wiki_compilation_model) == before

    def test_overrides_both(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_EVAL_PROVIDER", "openrouter")
        monkeypatch.setenv("HYDRAFLOW_EVAL_MODEL", "deepseek/deepseek-chat")
        cfg = HydraFlowConfig()
        apply_provider_override(cfg, provider_field=_PF, model_field=_MF)
        assert cfg.wiki_compilation_provider == "openrouter"
        assert cfg.wiki_compilation_model == "deepseek/deepseek-chat"

    def test_provider_only_leaves_model(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_EVAL_PROVIDER", "openrouter")
        monkeypatch.delenv("HYDRAFLOW_EVAL_MODEL", raising=False)
        cfg = HydraFlowConfig()
        original_model = cfg.wiki_compilation_model
        apply_provider_override(cfg, provider_field=_PF, model_field=_MF)
        assert cfg.wiki_compilation_provider == "openrouter"
        assert cfg.wiki_compilation_model == original_model


class TestBackendLabel:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_EVAL_PROVIDER", raising=False)
        monkeypatch.delenv("HYDRAFLOW_EVAL_MODEL", raising=False)
        assert "default" in backend_label()

    def test_labeled_when_set(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_EVAL_PROVIDER", "openrouter")
        monkeypatch.setenv("HYDRAFLOW_EVAL_MODEL", "x/y")
        assert backend_label() == "openrouter:x/y"
