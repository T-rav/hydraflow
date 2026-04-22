"""Tests for agent-drafted ADR workflow."""

from __future__ import annotations

from wiki_compiler import parse_adr_draft_suggestion


def test_parse_adr_draft_suggestion_basic():
    transcript = """Implementing the feature now.

ADR_DRAFT_SUGGESTION:
title: Always use Pydantic BaseModel for configs
context: Multiple issues (#123, #456) have shown that config classes written as
  dataclasses drift from the validation we get from Pydantic.
decision: Require config classes to subclass BaseModel.
consequences: Slightly more boilerplate; catches validation bugs at construction.
evidence:
  - issue: 123
  - issue: 456
  - wiki_entry: 01HQ0000000000000000000000
"""
    parsed = parse_adr_draft_suggestion(transcript)
    assert parsed is not None
    assert parsed["title"] == "Always use Pydantic BaseModel for configs"
    assert "dataclasses" in parsed["context"]
    assert parsed["evidence_issues"] == [123, 456]
    assert parsed["evidence_wiki_entries"] == ["01HQ0000000000000000000000"]


def test_parse_adr_draft_suggestion_returns_none_when_absent():
    assert parse_adr_draft_suggestion("no suggestion block here") is None


def test_parse_adr_draft_suggestion_tolerates_missing_evidence():
    transcript = """ADR_DRAFT_SUGGESTION:
title: X
context: Y
decision: Z
consequences: W
"""
    parsed = parse_adr_draft_suggestion(transcript)
    assert parsed is not None
    assert parsed["evidence_issues"] == []


from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def compiler():
    from wiki_compiler import WikiCompiler

    config = MagicMock()
    config.wiki_compilation_tool = "claude"
    config.wiki_compilation_model = "haiku"
    config.wiki_compilation_timeout = 30
    runner = MagicMock()
    creds = MagicMock()
    creds.gh_token = "fake-token"
    return WikiCompiler(config=config, runner=runner, credentials=creds)


@pytest.mark.asyncio
async def test_judge_adr_draft_all_gates_pass(compiler, tmp_path):
    from repo_wiki import WikiEntry
    from tribal_wiki import TribalWikiStore

    tribal = TribalWikiStore(tmp_path / "tribal")
    tribal_entry_id = "01HQ0000000000000000000000"
    tribal.ingest(
        [
            WikiEntry(
                id=tribal_entry_id,
                title="Pattern",
                content="Pattern body.",
                source_type="librarian",
                topic="patterns",
            )
        ]
    )

    suggestion = {
        "title": "X",
        "context": "Y",
        "decision": "Z",
        "consequences": "W",
        "evidence_issues": [1, 2],
        "evidence_wiki_entries": [tribal_entry_id],
    }
    compiler._call_model = AsyncMock(
        return_value=(
            '{"architectural": true, "load_bearing": true, "reason": "system-level"}'
        )
    )

    decision = await compiler.judge_adr_draft(
        suggestion=suggestion,
        tribal=tribal,
    )
    assert decision.two_plus_issues is True
    assert decision.in_tribal is True
    assert decision.architectural is True
    assert decision.load_bearing is True
    assert decision.draft_ok is True


@pytest.mark.asyncio
async def test_judge_adr_draft_single_issue_fails_gate_1(compiler, tmp_path):
    from tribal_wiki import TribalWikiStore

    tribal = TribalWikiStore(tmp_path / "tribal")
    suggestion = {
        "title": "X",
        "context": "Y",
        "decision": "Z",
        "consequences": "W",
        "evidence_issues": [1],
        "evidence_wiki_entries": [],
    }
    compiler._call_model = AsyncMock()
    decision = await compiler.judge_adr_draft(
        suggestion=suggestion,
        tribal=tribal,
    )
    assert decision.two_plus_issues is False
    assert decision.draft_ok is False
    compiler._call_model.assert_not_called()


@pytest.mark.asyncio
async def test_judge_adr_draft_missing_from_tribal_fails_gate_2(compiler, tmp_path):
    from tribal_wiki import TribalWikiStore

    tribal = TribalWikiStore(tmp_path / "tribal")  # empty
    suggestion = {
        "title": "X",
        "context": "Y",
        "decision": "Z",
        "consequences": "W",
        "evidence_issues": [1, 2],
        "evidence_wiki_entries": ["01HQ9999999999999999999999"],
    }
    compiler._call_model = AsyncMock()
    decision = await compiler.judge_adr_draft(
        suggestion=suggestion,
        tribal=tribal,
    )
    assert decision.in_tribal is False
    assert decision.draft_ok is False
    compiler._call_model.assert_not_called()


@pytest.mark.asyncio
async def test_judge_adr_draft_llm_says_not_architectural(compiler, tmp_path):
    from repo_wiki import WikiEntry
    from tribal_wiki import TribalWikiStore

    tribal = TribalWikiStore(tmp_path / "tribal")
    tid = "01HQ0000000000000000000000"
    tribal.ingest(
        [
            WikiEntry(
                id=tid,
                title="p",
                content="p",
                source_type="librarian",
                topic="patterns",
            )
        ]
    )
    suggestion = {
        "title": "X",
        "context": "Y",
        "decision": "Z",
        "consequences": "W",
        "evidence_issues": [1, 2],
        "evidence_wiki_entries": [tid],
    }
    compiler._call_model = AsyncMock(
        return_value=(
            '{"architectural": false, "load_bearing": true, "reason": "operational"}'
        )
    )
    decision = await compiler.judge_adr_draft(
        suggestion=suggestion,
        tribal=tribal,
    )
    assert decision.architectural is False
    assert decision.draft_ok is False
