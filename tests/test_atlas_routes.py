"""Tests for /api/atlas/* routes — the Atlas knowledge-graph dashboard surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from config import HydraFlowConfig
from events import EventBus
from state import StateTracker
from tests.helpers import find_endpoint, make_dashboard_router
from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermRel,
    TermRelKind,
    TermStore,
)


@pytest.fixture
def terms_root(tmp_path: Path) -> Path:
    """A docs/wiki/terms/ tree with 2 terms — one with an edge."""
    root = tmp_path / "docs" / "wiki" / "terms"
    store = TermStore(root)

    target = Term(
        id="01TARGET00000000000000",
        name="EventBus",
        kind=TermKind.SERVICE,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition="Async pub/sub bus.",
        invariants=["Bounded history."],
        code_anchor="src/events.py:EventBus",
        confidence="accepted",
    )
    store.write(target)

    source = Term(
        id="01SOURCE00000000000000",
        name="AgentRunner",
        kind=TermKind.RUNNER,
        bounded_context=BoundedContext.BUILDER,
        definition="Subprocess runner for the implement phase.",
        invariants=["_phase_name == 'implement'."],
        code_anchor="src/agent.py:AgentRunner",
        related=[TermRel(kind=TermRelKind.DEPENDS_ON, target=target.id)],
        confidence="accepted",
    )
    store.write(source)

    return root


@pytest.fixture
def config_with_terms(tmp_path: Path, terms_root: Path) -> HydraFlowConfig:
    """A HydraFlowConfig whose repo_root is the parent of docs/wiki/terms/."""
    return HydraFlowConfig(repo_root=tmp_path)


def _make_router(tmp_path: Path, config: HydraFlowConfig):
    state = StateTracker(tmp_path / "state.json")
    bus = EventBus()
    router, _ = make_dashboard_router(config, bus, state, tmp_path)
    return router


class TestAtlasTermsList:
    """GET /api/atlas/terms — list of summary records."""

    def test_returns_summaries_for_each_term(
        self, tmp_path: Path, config_with_terms: HydraFlowConfig
    ) -> None:
        router = _make_router(tmp_path, config_with_terms)
        endpoint = find_endpoint(router, "/api/atlas/terms", method="GET")
        assert endpoint is not None, "endpoint not registered"

        result = endpoint()

        assert len(result) == 2
        names = {t["name"] for t in result}
        assert names == {"AgentRunner", "EventBus"}

        agent = next(t for t in result if t["name"] == "AgentRunner")
        assert agent["kind"] == "runner"
        assert agent["bounded_context"] == "builder"
        assert agent["code_anchor"] == "src/agent.py:AgentRunner"
        assert agent["confidence"] == "accepted"
        assert agent["id"] == "01SOURCE00000000000000"

    def test_empty_when_terms_root_missing(self, tmp_path: Path) -> None:
        config = HydraFlowConfig(repo_root=tmp_path)
        router = _make_router(tmp_path, config)
        endpoint = find_endpoint(router, "/api/atlas/terms", method="GET")
        assert endpoint() == []


class TestAtlasTermDetail:
    """GET /api/atlas/terms/{id} — single term with definition + invariants."""

    def test_returns_full_term_for_known_id(
        self, tmp_path: Path, config_with_terms: HydraFlowConfig
    ) -> None:
        router = _make_router(tmp_path, config_with_terms)
        endpoint = find_endpoint(router, "/api/atlas/terms/{term_id}", method="GET")
        assert endpoint is not None

        result = endpoint(term_id="01SOURCE00000000000000")

        assert result["name"] == "AgentRunner"
        assert result["definition"].startswith("Subprocess runner")
        assert result["invariants"] == ["_phase_name == 'implement'."]
        assert result["aliases"] == []
        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["kind"] == "depends_on"
        assert edge["target_id"] == "01TARGET00000000000000"
        assert edge["target_name"] == "EventBus"

    def test_returns_404_for_unknown_id(
        self, tmp_path: Path, config_with_terms: HydraFlowConfig
    ) -> None:
        router = _make_router(tmp_path, config_with_terms)
        endpoint = find_endpoint(router, "/api/atlas/terms/{term_id}", method="GET")
        with pytest.raises(HTTPException) as exc:
            endpoint(term_id="01NOPE0000000000000000")
        assert exc.value.status_code == 404


class TestAtlasGraph:
    """GET /api/atlas/graph — pre-computed nodes + edges + contexts."""

    def test_returns_grouped_payload(
        self, tmp_path: Path, config_with_terms: HydraFlowConfig
    ) -> None:
        router = _make_router(tmp_path, config_with_terms)
        endpoint = find_endpoint(router, "/api/atlas/graph", method="GET")
        assert endpoint is not None

        result = endpoint()

        assert {c["id"] for c in result["contexts"]} == {"builder", "shared-kernel"}

        assert len(result["nodes"]) == 2
        agent_node = next(n for n in result["nodes"] if n["name"] == "AgentRunner")
        assert agent_node["parent"] == "builder"
        assert agent_node["kind"] == "runner"
        assert agent_node["confidence"] == "accepted"

        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["kind"] == "depends_on"
        assert edge["source"] == "01SOURCE00000000000000"
        assert edge["target"] == "01TARGET00000000000000"

    def test_empty_graph_when_no_terms(self, tmp_path: Path) -> None:
        config = HydraFlowConfig(repo_root=tmp_path)
        router = _make_router(tmp_path, config)
        endpoint = find_endpoint(router, "/api/atlas/graph", method="GET")
        result = endpoint()
        assert result == {"nodes": [], "edges": [], "contexts": []}


class TestAtlasAdrsList:
    """GET /api/atlas/adrs — minimal summary records from docs/adr/*.md."""

    @pytest.fixture
    def adr_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "docs" / "adr"
        root.mkdir(parents=True)
        (root / "0001-first.md").write_text(
            "# ADR-0001: First decision\n\n"
            "## Status\n\nAccepted\n\n"
            "## Date\n\n2026-01-15\n\n"
            "## Context\n\nSomething.\n"
        )
        (root / "0002-second.md").write_text(
            "# ADR-0002: Second decision\n\n"
            "## Status\n\nProposed\n\n"
            "## Date\n\n2026-02-20\n\n"
            "## Context\n\nAnother thing.\n"
        )
        (root / "README.md").write_text("# ADR Index\n\nIgnored.\n")
        return root

    def test_returns_summaries_skipping_readme(
        self, tmp_path: Path, adr_root: Path
    ) -> None:
        config = HydraFlowConfig(repo_root=tmp_path)
        router = _make_router(tmp_path, config)
        endpoint = find_endpoint(router, "/api/atlas/adrs", method="GET")
        assert endpoint is not None

        result = endpoint()

        assert len(result) == 2
        first = next(r for r in result if r["number"] == 1)
        assert first["title"] == "First decision"
        assert first["status"] == "Accepted"
        assert first["date"] == "2026-01-15"

        second = next(r for r in result if r["number"] == 2)
        assert second["status"] == "Proposed"

    def test_empty_when_adr_dir_missing(self, tmp_path: Path) -> None:
        config = HydraFlowConfig(repo_root=tmp_path)
        router = _make_router(tmp_path, config)
        endpoint = find_endpoint(router, "/api/atlas/adrs", method="GET")
        assert endpoint() == []


class TestAtlasAdrDetail:
    """GET /api/atlas/adrs/{number} — full markdown body + parsed metadata."""

    def test_returns_full_adr(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        body = (
            "# ADR-0042: Test decision\n\n"
            "## Status\n\nAccepted\n\n"
            "## Date\n\n2026-03-15\n\n"
            "## Context\n\nReasoning.\n\n"
            "## Related\n\n- ADR-0001 — First decision\n- `src/foo.py:Bar`\n"
        )
        (adr_dir / "0042-test-decision.md").write_text(body)

        config = HydraFlowConfig(repo_root=tmp_path)
        router = _make_router(tmp_path, config)
        endpoint = find_endpoint(router, "/api/atlas/adrs/{number}", method="GET")
        assert endpoint is not None

        result = endpoint(number=42)

        assert result["number"] == 42
        assert result["title"] == "Test decision"
        assert result["status"] == "Accepted"
        assert result["date"] == "2026-03-15"
        assert "Reasoning." in result["body"]
        assert isinstance(result["related"], list)
        assert len(result["related"]) == 2

    def test_returns_404_for_unknown_number(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "adr").mkdir(parents=True)
        config = HydraFlowConfig(repo_root=tmp_path)
        router = _make_router(tmp_path, config)
        endpoint = find_endpoint(router, "/api/atlas/adrs/{number}", method="GET")
        with pytest.raises(HTTPException) as exc:
            endpoint(number=9999)
        assert exc.value.status_code == 404
