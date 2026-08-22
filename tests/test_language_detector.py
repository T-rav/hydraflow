"""Tests for target-repo language detection via marker files."""

from __future__ import annotations

from pathlib import Path

import pytest

from language_detector import detect_languages


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


class TestDetectLanguages:
    @pytest.mark.parametrize(
        ("marker", "content", "expected"),
        [
            pytest.param(
                "pyproject.toml",
                "[project]\nname = 'x'\n",
                {"python"},
                id="python_from_pyproject_toml",
            ),
            pytest.param(
                "setup.py",
                "from setuptools import setup\n",
                {"python"},
                id="python_from_setup_py",
            ),
            pytest.param(
                "requirements.txt",
                "requests==2.0\n",
                {"python"},
                id="python_from_requirements_txt",
            ),
            pytest.param(
                "tsconfig.json", "{}\n", {"typescript"}, id="typescript_from_tsconfig"
            ),
            # typescript counts whether it is declared as a dev or a runtime dep.
            pytest.param(
                "package.json",
                '{"devDependencies": {"typescript": "^5.0.0"}}\n',
                {"typescript"},
                id="typescript_from_package_json_with_ts_dep",
            ),
            pytest.param(
                "package.json",
                '{"dependencies": {"typescript": "^5.0.0"}}\n',
                {"typescript"},
                id="typescript_from_package_json_dependencies",
            ),
            pytest.param(
                "MyApp.csproj",
                "<Project></Project>\n",
                {"csharp"},
                id="csharp_from_csproj",
            ),
            pytest.param(
                "MyApp.sln",
                "Microsoft Visual Studio Solution\n",
                {"csharp"},
                id="csharp_from_sln",
            ),
            pytest.param(
                "go.mod", "module example.com/foo\n", {"go"}, id="go_from_go_mod"
            ),
            pytest.param(
                "Cargo.toml",
                "[package]\nname = 'x'\n",
                {"rust"},
                id="rust_from_cargo_toml",
            ),
        ],
    )
    def test_marker_file_detects_language(
        self, repo: Path, marker: str, content: str, expected: set[str]
    ) -> None:
        """Each marker file, alone in the repo, detects exactly its language."""
        (repo / marker).write_text(content)
        assert detect_languages(repo) == expected

    def test_package_json_without_typescript_dep_is_not_typescript(
        self, repo: Path
    ) -> None:
        """package.json without typescript dependency should not detect typescript."""
        (repo / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}\n')
        assert detect_languages(repo) == set()

    def test_multi_language_returns_all(self, repo: Path) -> None:
        """Multiple marker files should return all detected languages."""
        (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (repo / "tsconfig.json").write_text("{}\n")
        assert detect_languages(repo) == {"python", "typescript"}

    def test_empty_repo_returns_empty_set(self, repo: Path) -> None:
        """A directory with no marker files should return an empty set."""
        assert detect_languages(repo) == set()

    def test_nonexistent_path_returns_empty_set(self, repo: Path) -> None:
        """A nonexistent path should return an empty set, not raise."""
        assert detect_languages(repo / "does-not-exist") == set()

    def test_malformed_package_json_is_not_typescript(self, repo: Path) -> None:
        """Malformed package.json should be treated as no typescript dependency."""
        (repo / "package.json").write_text("{not valid json")
        assert detect_languages(repo) == set()
