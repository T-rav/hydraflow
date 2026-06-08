"""D2 data-layout migration — per-repo operational stores move to repo_data_root.

Covers the new repo-scoped config accessors and the one-time idempotent
migration that relocates legacy flat ``data_root/<store>`` content into the
repo-scoped ``data_root/<repo_slug>/<store>`` layout. See ADR-0021 (amended).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from config import HydraFlowConfig
from data_migration import migrate_flat_operational_stores


def _cfg(tmp_path: Path, repo: str = "acme/widgets") -> HydraFlowConfig:
    return HydraFlowConfig(repo_root=tmp_path, repo=repo)


class TestRepoScopedAccessors:
    """New config accessors resolve in-scope stores under data_root/<repo_slug>."""

    def test_repo_data_path_joins_under_repo_data_root(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.repo_data_path("runs") == cfg.repo_data_root / "runs"
        assert cfg.repo_data_path("metrics", "prompt") == (
            cfg.repo_data_root / "metrics" / "prompt"
        )

    def test_repo_memory_dir_is_scoped(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.repo_memory_dir == cfg.repo_data_root / "memory"
        assert "acme-widgets" in str(cfg.repo_memory_dir)

    def test_retrospectives_path_is_scoped(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.retrospectives_path == (
            cfg.repo_data_root / "memory" / "retrospectives.jsonl"
        )

    def test_cost_inferences_path_is_scoped(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.cost_inferences_path == (
            cfg.repo_data_root / "metrics" / "prompt" / "inferences.jsonl"
        )

    def test_pr_stats_path_is_scoped(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.pr_stats_path == (
            cfg.repo_data_root / "metrics" / "prompt" / "pr_stats.json"
        )

    def test_factory_metrics_path_is_scoped(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert cfg.factory_metrics_path == (
            cfg.repo_data_root / "diagnostics" / "factory_metrics.jsonl"
        )
        # No longer flat under data_root/diagnostics.
        assert cfg.factory_metrics_path != cfg.data_root / "diagnostics" / (
            "factory_metrics.jsonl"
        )

    def test_two_repos_get_separate_store_paths(self, tmp_path: Path) -> None:
        cfg_a = _cfg(tmp_path, repo="org/alpha")
        cfg_b = _cfg(tmp_path, repo="org/beta")
        for accessor in (
            "retrospectives_path",
            "cost_inferences_path",
            "factory_metrics_path",
            "repo_memory_dir",
        ):
            assert getattr(cfg_a, accessor) != getattr(cfg_b, accessor)


class TestFlatStoreMigration:
    """Legacy flat stores are copied into the repo-scoped layout."""

    def test_runs_tree_migrated(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat_run = cfg.data_root / "runs" / "42" / "20260101-000000"
        flat_run.mkdir(parents=True)
        (flat_run / "manifest.json").write_text('{"issue": 42}')

        migrate_flat_operational_stores(cfg)

        scoped = (
            cfg.repo_data_root / "runs" / "42" / "20260101-000000" / "manifest.json"
        )
        assert scoped.exists()
        assert scoped.read_text() == '{"issue": 42}'

    def test_cost_inferences_and_pr_stats_migrated(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat_dir = cfg.data_root / "metrics" / "prompt"
        flat_dir.mkdir(parents=True)
        (flat_dir / "inferences.jsonl").write_text('{"cost_usd": 1.0}\n')
        (flat_dir / "pr_stats.json").write_text('{"pr": 1}')

        migrate_flat_operational_stores(cfg)

        assert cfg.cost_inferences_path.read_text() == '{"cost_usd": 1.0}\n'
        assert cfg.pr_stats_path.read_text() == '{"pr": 1}'

    def test_factory_metrics_migrated(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat = cfg.data_root / "diagnostics" / "factory_metrics.jsonl"
        flat.parent.mkdir(parents=True)
        flat.write_text('{"event": "phase"}\n')

        migrate_flat_operational_stores(cfg)

        assert cfg.factory_metrics_path.read_text() == '{"event": "phase"}\n'

    def test_retrospective_family_migrated(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat_mem = cfg.data_root / "memory"
        flat_mem.mkdir(parents=True)
        (flat_mem / "retrospectives.jsonl").write_text('{"issue": 7}\n')
        (flat_mem / "filed_patterns.json").write_text('["p1"]')
        (flat_mem / "retrospective_queue.jsonl").write_text('{"kind": "verify"}\n')

        migrate_flat_operational_stores(cfg)

        scoped_mem = cfg.repo_memory_dir
        assert (scoped_mem / "retrospectives.jsonl").read_text() == '{"issue": 7}\n'
        assert (scoped_mem / "filed_patterns.json").read_text() == '["p1"]'
        assert (scoped_mem / "retrospective_queue.jsonl").exists()

    def test_harness_family_migrated(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat_mem = cfg.data_root / "memory"
        flat_mem.mkdir(parents=True)
        (flat_mem / "harness_failures.jsonl").write_text('{"stage": "ci"}\n')
        (flat_mem / "harness_suggestions.jsonl").write_text('{"hint": "x"}\n')
        (flat_mem / "harness_proposed.json").write_text('["k1"]')

        migrate_flat_operational_stores(cfg)

        scoped_mem = cfg.repo_memory_dir
        assert (
            scoped_mem / "harness_failures.jsonl"
        ).read_text() == '{"stage": "ci"}\n'
        assert (scoped_mem / "harness_suggestions.jsonl").exists()
        assert (scoped_mem / "harness_proposed.json").read_text() == '["k1"]'

    def test_review_family_migrated(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat_mem = cfg.data_root / "memory"
        flat_mem.mkdir(parents=True)
        (flat_mem / "reviews.jsonl").write_text('{"pr": 99}\n')
        (flat_mem / "proposed_categories.json").write_text('["nit"]')
        (flat_mem / "proposal_metadata.json").write_text('{"nit": {}}')

        migrate_flat_operational_stores(cfg)

        scoped_mem = cfg.repo_memory_dir
        assert (scoped_mem / "reviews.jsonl").read_text() == '{"pr": 99}\n'
        assert (scoped_mem / "proposed_categories.json").read_text() == '["nit"]'
        assert (scoped_mem / "proposal_metadata.json").exists()

    def test_host_shared_memory_files_not_migrated(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat_mem = cfg.data_root / "memory"
        flat_mem.mkdir(parents=True)
        # Out-of-scope host-shared stores must stay flat.
        (flat_mem / "adr_decisions.jsonl").write_text('{"adr": 1}\n')
        (flat_mem / "hitl_recommendations.jsonl").write_text('{"rec": 1}\n')
        (flat_mem / "items.jsonl").write_text('{"item": 1}\n')
        (flat_mem / "verification_records.jsonl").write_text('{"v": 1}\n')

        migrate_flat_operational_stores(cfg)

        scoped_mem = cfg.repo_memory_dir
        for name in (
            "adr_decisions.jsonl",
            "hitl_recommendations.jsonl",
            "items.jsonl",
            "verification_records.jsonl",
        ):
            assert not (scoped_mem / name).exists()


class TestMigrationIdempotency:
    """Migration never overwrites already-scoped data and is safe to re-run."""

    def test_does_not_overwrite_existing_scoped_file(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat = cfg.data_root / "diagnostics" / "factory_metrics.jsonl"
        flat.parent.mkdir(parents=True)
        flat.write_text('{"old": true}\n')
        cfg.factory_metrics_path.parent.mkdir(parents=True)
        cfg.factory_metrics_path.write_text('{"new": true}\n')

        migrate_flat_operational_stores(cfg)

        assert cfg.factory_metrics_path.read_text() == '{"new": true}\n'

    def test_does_not_overwrite_existing_scoped_runs_tree(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        (cfg.data_root / "runs" / "1").mkdir(parents=True)
        (cfg.data_root / "runs" / "1" / "old.txt").write_text("old")
        scoped_runs = cfg.repo_data_root / "runs"
        (scoped_runs / "2").mkdir(parents=True)
        (scoped_runs / "2" / "new.txt").write_text("new")

        migrate_flat_operational_stores(cfg)

        # Existing scoped tree is left intact; flat tree is not merged in.
        assert (scoped_runs / "2" / "new.txt").exists()
        assert not (scoped_runs / "1" / "old.txt").exists()

    def test_second_run_is_a_noop(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        flat = cfg.data_root / "memory" / "retrospectives.jsonl"
        flat.parent.mkdir(parents=True)
        flat.write_text('{"issue": 1}\n')

        migrate_flat_operational_stores(cfg)
        # Mutate the scoped copy; a second run must not re-copy over it.
        cfg.retrospectives_path.write_text('{"issue": 2}\n')
        migrate_flat_operational_stores(cfg)

        assert cfg.retrospectives_path.read_text() == '{"issue": 2}\n'


class TestMigrationResilience:
    """A copy failure logs and continues — startup must never crash on migration."""

    def test_copy_failure_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _cfg(tmp_path)
        flat = cfg.data_root / "memory" / "retrospectives.jsonl"
        flat.parent.mkdir(parents=True)
        flat.write_text('{"issue": 1}\n')

        def fail_copy(src: object, dst: object, **kw: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(shutil, "copy2", fail_copy)

        migrate_flat_operational_stores(cfg)  # must not raise
        assert not cfg.retrospectives_path.exists()

    def test_tree_copy_failure_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _cfg(tmp_path)
        flat_run = cfg.data_root / "runs" / "5"
        flat_run.mkdir(parents=True)
        (flat_run / "manifest.json").write_text("{}")

        def fail_tree(src: object, dst: object, **kw: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(shutil, "copytree", fail_tree)

        migrate_flat_operational_stores(cfg)  # must not raise
        assert not (cfg.repo_data_root / "runs").exists()


class TestMigrationScoping:
    """Migration is a no-op when there is no repo slug to scope under."""

    def test_noop_when_repo_data_root_equals_data_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _cfg(tmp_path)
        # Force the degenerate case where scoping would copy onto itself.
        monkeypatch.setattr(
            type(cfg), "repo_data_root", property(lambda self: self.data_root)
        )
        flat = cfg.data_root / "memory" / "retrospectives.jsonl"
        flat.parent.mkdir(parents=True)
        flat.write_text("{}\n")

        migrate_flat_operational_stores(cfg)  # must not raise or self-copy

        assert flat.read_text() == "{}\n"

    def test_two_repos_isolate_migrated_data(self, tmp_path: Path) -> None:
        # Legacy flat data belongs to whichever config migrates it; each repo
        # only ever migrates into its own slug.
        flat_mem = tmp_path / ".hydraflow" / "memory"
        flat_mem.mkdir(parents=True)
        (flat_mem / "reviews.jsonl").write_text('{"pr": 1}\n')

        cfg_a = _cfg(tmp_path, repo="org/alpha")
        migrate_flat_operational_stores(cfg_a)

        cfg_b = _cfg(tmp_path, repo="org/beta")
        # Beta has its own (empty) scoped memory; alpha got the legacy data.
        assert (cfg_a.repo_memory_dir / "reviews.jsonl").exists()
        assert cfg_a.repo_memory_dir != cfg_b.repo_memory_dir
