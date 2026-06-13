"""Tests for null_delivery — the diagrams-only / auto-generated-only classifier."""

from __future__ import annotations

from null_delivery import (
    is_non_deliverable_path,
    is_null_delivery,
    substantive_paths,
)


class TestIsNonDeliverablePath:
    def test_planner_likec4_diagram_is_non_deliverable(self) -> None:
        assert is_non_deliverable_path("docs/architecture/model_pricing.likec4")

    def test_repo_wiki_ingest_is_non_deliverable(self) -> None:
        assert is_non_deliverable_path("repo_wiki/T-rav/hydraflow/log/9443.jsonl")

    def test_generated_arch_artifact_is_non_deliverable(self) -> None:
        assert is_non_deliverable_path("docs/arch/generated/changelog.md")

    def test_arch_meta_json_is_non_deliverable(self) -> None:
        assert is_non_deliverable_path("docs/arch/.meta.json")

    def test_source_file_is_deliverable(self) -> None:
        assert not is_non_deliverable_path("src/model_pricing.py")

    def test_test_file_is_deliverable(self) -> None:
        assert not is_non_deliverable_path("tests/test_model_pricing.py")

    def test_asset_file_is_deliverable(self) -> None:
        assert not is_non_deliverable_path("src/assets/model_pricing.json")

    def test_real_doc_markdown_is_deliverable(self) -> None:
        assert not is_non_deliverable_path("docs/adr/0099-new-decision.md")

    def test_non_likec4_under_architecture_is_deliverable(self) -> None:
        assert not is_non_deliverable_path("docs/architecture/README.md")

    def test_leading_dot_slash_is_handled(self) -> None:
        assert is_non_deliverable_path("./docs/architecture/component.likec4")


class TestSubstantivePaths:
    def test_filters_out_non_deliverables(self) -> None:
        paths = [
            "docs/architecture/component.likec4",
            "repo_wiki/T-rav/hydraflow/patterns/0008-x.md",
            "src/contracts/shadow_classifier.py",
            "tests/test_shadow_classifier.py",
        ]
        assert substantive_paths(paths) == [
            "src/contracts/shadow_classifier.py",
            "tests/test_shadow_classifier.py",
        ]

    def test_returns_empty_for_diagrams_only(self) -> None:
        assert substantive_paths(["docs/architecture/parity-guard.likec4"]) == []


class TestIsNullDelivery:
    def test_diagram_only_diff_is_null_delivery(self) -> None:
        assert is_null_delivery(["docs/architecture/fake-github-contract.likec4"])

    def test_diagrams_plus_wiki_notes_is_null_delivery(self) -> None:
        assert is_null_delivery(
            [
                "docs/architecture/pipeline_poller_flows.likec4",
                "docs/architecture/pipeline_poller_scenario.likec4",
                "repo_wiki/T-rav/hydraflow/testing/0007-x.md",
                "repo_wiki/T-rav/hydraflow/log/9441.jsonl",
            ]
        )

    def test_real_code_diff_is_not_null_delivery(self) -> None:
        assert not is_null_delivery(
            [
                "src/contracts/shadow_classifier.py",
                "tests/test_shadow_classifier.py",
                "docs/architecture/01-component-shadow-classifier.likec4",
            ]
        )

    def test_asset_only_change_is_not_null_delivery(self) -> None:
        assert not is_null_delivery(["src/assets/model_pricing.json"])

    def test_real_docs_change_is_not_null_delivery(self) -> None:
        assert not is_null_delivery(["docs/adr/0099-new-decision.md"])

    def test_empty_diff_is_not_null_delivery(self) -> None:
        assert not is_null_delivery([])

    def test_blank_entries_only_is_not_null_delivery(self) -> None:
        assert not is_null_delivery(["", "  "])
