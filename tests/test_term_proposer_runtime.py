"""Tests for the production adapters wiring TermProposerLoop."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from term_proposer_runtime import (
    _UL_CONTEXT_MAP_REL,
    _UL_GLOSSARY_REL,
    ClaudeCLIClient,
    OpenAutoPRBotPRPort,
    regenerate_ubiquitous_language_artifacts,
)


def _term_file_str(name: str) -> str:
    """Render one minimal Term to its canonical on-disk markdown form."""
    from term_proposer_loop import _render_term_file_str
    from ubiquitous_language import BoundedContext, Term, TermKind

    term = Term(
        name=name,
        kind=TermKind.LOOP,
        bounded_context=BoundedContext.CARETAKER,
        code_anchor=f"src/{name.lower()}.py:{name}",
        definition=f"{name} does a thing.",
    )
    return _render_term_file_str(term)


class FakeRunner:
    def __init__(self, *, returncode: int, stdout: str, stderr: str = "") -> None:
        self._result = subprocess.CompletedProcess(
            args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr
        )
        self.calls: list[dict] = []

    async def run_simple(
        self, cmd, *, input=None, timeout=None, **_
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append({"cmd": cmd, "input": input, "timeout": timeout})
        return self._result


class TestClaudeCLIClient:
    @pytest.mark.asyncio
    async def test_returns_parsed_json(self) -> None:
        runner = FakeRunner(returncode=0, stdout='{"foo": "bar", "n": 1}')
        client = ClaudeCLIClient(runner=runner)
        out = await client.complete_structured(prompt="hi", schema={})
        assert out == {"foo": "bar", "n": 1}

    @pytest.mark.asyncio
    async def test_extracts_json_from_markdown_fence(self) -> None:
        runner = FakeRunner(
            returncode=0,
            stdout='Here is the result:\n```json\n{"k": "v"}\n```\nDone.',
        )
        client = ClaudeCLIClient(runner=runner)
        out = await client.complete_structured(prompt="hi", schema={})
        assert out == {"k": "v"}

    @pytest.mark.asyncio
    async def test_raises_on_nonzero_returncode(self) -> None:
        runner = FakeRunner(returncode=1, stdout="", stderr="boom")
        client = ClaudeCLIClient(runner=runner)
        with pytest.raises(RuntimeError, match="claude CLI failed"):
            await client.complete_structured(prompt="hi", schema={})

    @pytest.mark.asyncio
    async def test_raises_when_no_json_in_output(self) -> None:
        runner = FakeRunner(returncode=0, stdout="just prose, no json here")
        client = ClaudeCLIClient(runner=runner)
        with pytest.raises(RuntimeError, match="no JSON object"):
            await client.complete_structured(prompt="hi", schema={})


class TestOpenAutoPRBotPRPort:
    @pytest.mark.asyncio
    async def test_generates_in_worktree_and_returns_pr_number(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # The bot PR is opened via generate-in-worktree (#9539); repo_root is
        # never written to. The generate callback is NOT invoked when
        # generate_and_open_pr_async is mocked, so we assert the call kwargs.
        from auto_pr import AutoPrResult

        captured: dict = {}

        async def fake_generate_and_open_pr_async(**kwargs):
            captured.update(kwargs)
            return AutoPrResult(
                status="opened",
                pr_url="https://github.com/T-rav/hydraflow/pull/4242",
                branch=kwargs["branch"],
            )

        monkeypatch.setattr(
            "auto_pr.generate_and_open_pr_async", fake_generate_and_open_pr_async
        )

        port = OpenAutoPRBotPRPort(repo_root=tmp_path, gh_token="ghs_x")
        files = {
            "docs/wiki/terms/foo-loop.md": _term_file_str("FooLoop"),
            "docs/wiki/terms/bar-runner.md": _term_file_str("BarRunner"),
        }
        pr_number = await port.open_bot_pr(
            branch="ul-proposer/abc123",
            title="feat(ul): batch",
            body="body",
            labels=["hydraflow-ul-proposed"],
            files=files,
        )

        assert pr_number == 4242
        # repo_root stays clean — nothing is written under it (#9539).
        assert not (tmp_path / "docs/wiki/terms/foo-loop.md").exists()
        assert not (tmp_path / "docs/arch/generated").exists()
        # auto_pr called with the right args
        assert captured["branch"] == "ul-proposer/abc123"
        assert captured["pr_title"] == "feat(ul): batch"
        assert captured["labels"] == ["hydraflow-ul-proposed"]
        assert captured["auto_merge"] is False  # DependabotMergeLoop handles merge
        assert captured["base"] == "main"  # default (single-tier / pre-staging)
        assert callable(captured["generate"])
        # 2 term files + the 2 regenerated ubiquitous-language views ride along.
        assert captured["path_specs"] == [
            "docs/wiki/terms/foo-loop.md",
            "docs/wiki/terms/bar-runner.md",
            _UL_GLOSSARY_REL,
            _UL_CONTEXT_MAP_REL,
        ]

    @pytest.mark.asyncio
    async def test_targets_configured_base_branch(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Regression (UL→main PR runaway): when staging is enabled the registry
        # passes config.base_branch()=="staging"; the bot PR MUST target it, not
        # a hardcoded "main". main-targeted PRs are BLOCKED by branch protection
        # (main only advances via rc/* promotion) and pile up unmerged.
        from auto_pr import AutoPrResult

        captured: dict = {}

        async def fake_generate_and_open_pr_async(**kwargs):
            captured.update(kwargs)
            return AutoPrResult(
                status="opened",
                pr_url="https://github.com/T-rav/hydraflow/pull/9001",
                branch=kwargs["branch"],
            )

        monkeypatch.setattr(
            "auto_pr.generate_and_open_pr_async", fake_generate_and_open_pr_async
        )

        port = OpenAutoPRBotPRPort(repo_root=tmp_path, gh_token="ghs_x", base="staging")
        await port.open_bot_pr(
            branch="ul-proposer/abc123",
            title="feat(ul): batch",
            body="body",
            labels=["hydraflow-ul-proposed"],
            files={"docs/wiki/terms/foo-loop.md": _term_file_str("FooLoop")},
        )

        assert captured["base"] == "staging"

    @pytest.mark.asyncio
    async def test_raises_on_open_failure(self, tmp_path: Path, monkeypatch) -> None:
        from auto_pr import AutoPrResult

        async def fake_generate_and_open_pr_async(**kwargs):
            return AutoPrResult(
                status="failed", pr_url=None, branch=kwargs["branch"], error="auth"
            )

        monkeypatch.setattr(
            "auto_pr.generate_and_open_pr_async", fake_generate_and_open_pr_async
        )

        port = OpenAutoPRBotPRPort(repo_root=tmp_path)
        with pytest.raises(RuntimeError, match="status='failed'"):
            await port.open_bot_pr(
                branch="x", title="x", body="x", labels=[], files={"foo.md": "x"}
            )

    @pytest.mark.asyncio
    async def test_generate_callback_regenerates_ul_artifacts_in_worktree(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # A term-proposer PR mutates docs/wiki/terms/ — the generated
        # ubiquitous-language views derive from those files, so the commit MUST
        # also carry the regenerated views or the pre-push arch-check drift
        # guard rejects the push. The generate callback writes the term file AND
        # regenerates the views INTO the worktree (never repo_root, #9539).
        from auto_pr import AutoPrResult

        captured: dict = {}

        async def fake_generate_and_open_pr_async(**kwargs):
            captured.update(kwargs)
            return AutoPrResult(
                status="opened",
                pr_url="https://github.com/T-rav/hydraflow/pull/77",
                branch=kwargs["branch"],
            )

        monkeypatch.setattr(
            "auto_pr.generate_and_open_pr_async", fake_generate_and_open_pr_async
        )

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        port = OpenAutoPRBotPRPort(repo_root=repo_root)
        await port.open_bot_pr(
            branch="ul-proposer/abc123",
            title="feat(ul): batch",
            body="body",
            labels=["hydraflow-ul-proposed"],
            files={"docs/wiki/terms/widget-maker.md": _term_file_str("WidgetMaker")},
        )

        # The term file + the two UL views are staged.
        assert captured["path_specs"] == [
            "docs/wiki/terms/widget-maker.md",
            _UL_GLOSSARY_REL,
            _UL_CONTEXT_MAP_REL,
        ]
        # Drive the generate callback against a real worktree dir: it must write
        # the term file and regenerate the views THERE — and leave repo_root
        # untouched (#9539).
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        await captured["generate"](worktree)

        assert (worktree / "docs/wiki/terms/widget-maker.md").exists()
        assert (worktree / _UL_GLOSSARY_REL).exists()
        assert (worktree / _UL_CONTEXT_MAP_REL).exists()
        # repo_root is never touched.
        assert not (repo_root / "docs/wiki/terms/widget-maker.md").exists()
        assert not (repo_root / "docs/arch/generated").exists()

    @pytest.mark.asyncio
    async def test_skips_regen_when_no_term_files_change(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Non-term bot PRs (no docs/wiki/terms/ file) must not trigger UL regen.
        from auto_pr import AutoPrResult

        captured: dict = {}

        async def fake_generate_and_open_pr_async(**kwargs):
            captured.update(kwargs)
            return AutoPrResult(
                status="opened",
                pr_url="https://github.com/T-rav/hydraflow/pull/88",
                branch=kwargs["branch"],
            )

        monkeypatch.setattr(
            "auto_pr.generate_and_open_pr_async", fake_generate_and_open_pr_async
        )

        port = OpenAutoPRBotPRPort(repo_root=tmp_path)
        await port.open_bot_pr(
            branch="x", title="x", body="x", labels=[], files={"docs/other.md": "x"}
        )

        # Only the non-term file is staged — no UL views ride along.
        assert captured["path_specs"] == ["docs/other.md"]
        # Drive the generate callback: it writes only the non-term file, no regen.
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        await captured["generate"](worktree)
        assert (worktree / "docs/other.md").exists()
        assert not (worktree / "docs/arch/generated").exists()


class TestRegenerateUbiquitousLanguageArtifacts:
    def test_renders_views_matching_canonical_generators(self, tmp_path: Path) -> None:
        from ubiquitous_language import (
            TermStore,
            render_context_map,
            render_glossary,
        )

        terms_dir = tmp_path / "docs" / "wiki" / "terms"
        terms_dir.mkdir(parents=True)
        (terms_dir / "widget-maker.md").write_text(
            _term_file_str("WidgetMaker"), encoding="utf-8"
        )
        (terms_dir / "gadget-runner.md").write_text(
            _term_file_str("GadgetRunner"), encoding="utf-8"
        )

        written = regenerate_ubiquitous_language_artifacts(tmp_path)

        terms = TermStore(terms_dir).list()
        glossary = tmp_path / "docs/arch/generated/ubiquitous-language.md"
        context_map = (
            tmp_path / "docs/arch/generated/ubiquitous-language-context-map.md"
        )
        assert set(written) == {glossary, context_map}
        # Byte-for-byte equal to the canonical generators — this is exactly what
        # `make arch-check` compares against, so a mismatch would re-trigger the
        # drift guard the fix exists to silence.
        assert glossary.read_text(encoding="utf-8") == render_glossary(terms)
        assert context_map.read_text(encoding="utf-8") == render_context_map(terms)

    def test_returns_empty_when_no_terms_dir(self, tmp_path: Path) -> None:
        assert regenerate_ubiquitous_language_artifacts(tmp_path) == []
