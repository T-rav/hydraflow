"""#11690 Layers 2 and 3: the sink adapter, and the one question it answers.

The emitter (#11689) writes a self-identifying document to stdout and knows
nothing about sinks. These tests cover the other side of that seam and, most
importantly, that the seam still exists: an adapter the emitter imported would
make swapping the sink a HydraFlow change, which is the thing Layer 2 is for.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from vitals_sink.degrading import (  # noqa: E402
    read_tree,
    regressions,
    report,
    silent,
)
from vitals_sink.layout import (  # noqa: E402
    SCHEMA_VERSION,
    VITALS_KIND,
    MalformedDocument,
    place,
    relative_path,
)

_REPO = Path(__file__).resolve().parents[1]


def _doc(
    *,
    repo: str = "acme/hydraflow",
    host: str = "box-1",
    emitted_at: str = "2026-09-01T12:00:00+00:00",
    sha: str = "abc1234def",
    **metrics: float,
) -> dict:
    return {
        "kind": VITALS_KIND,
        "schema_version": SCHEMA_VERSION,
        "emitted_at": emitted_at,
        "identity": {"repo": repo, "host": host, "head_sha": sha},
        "baselines": {"suppressions": dict(metrics)} if metrics else {},
    }


class TestTheSeamStillExists:
    """The property that makes Layer 2 swappable, asserted rather than assumed."""

    def test_the_emitter_does_not_import_the_adapter(self) -> None:
        tree = ast.parse((_REPO / "scripts" / "emit_vitals.py").read_text())
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }

        offenders = [name for name in imported if "vitals_sink" in name]

        assert not offenders, (
            f"the emitter imports the sink adapter ({offenders}); Layer 2 exists "
            f"so that swapping a sink is never a HydraFlow change, and an import "
            f"in this direction makes it one"
        )

    def test_the_kind_this_adapter_accepts_is_the_kind_the_emitter_writes(
        self,
    ) -> None:
        """Two writers, one vocabulary — pinned rather than hoped for."""
        result = subprocess.run(
            [sys.executable, str(_REPO / "scripts" / "emit_vitals.py")],
            capture_output=True,
            text=True,
            cwd=_REPO,
            env={"PYTHONPATH": str(_REPO / "src"), "PATH": "/usr/bin:/bin"},
            check=False,
        )
        emitted = json.loads(result.stdout)

        assert emitted["kind"] == VITALS_KIND
        assert emitted["schema_version"] == SCHEMA_VERSION


class TestThePathCarriesTheIdentity:
    def test_repo_host_and_date_are_all_in_the_path(self) -> None:
        path = relative_path(_doc()).as_posix()

        assert path.startswith("repo=acme_hydraflow/host=box-1/date=2026-09-01/")

    def test_two_hosts_at_one_sha_do_not_collide(self) -> None:
        """The failure a body-only identity would allow."""
        one = relative_path(_doc(host="box-1"))
        two = relative_path(_doc(host="box-2"))

        assert one != two

    def test_a_traversal_in_the_repo_slug_cannot_escape_the_root(
        self, tmp_path: Path
    ) -> None:
        """The property is where it RESOLVES, not whether ".." appears.

        A sanitised ``.._.._etc`` still contains the characters, and asserting
        on the spelling would fail a segment that is perfectly safe while
        saying nothing about the one that is not.
        """
        written = place(_doc(repo="../../etc"), root=tmp_path)

        assert written.resolve().is_relative_to(tmp_path.resolve())

    def test_an_all_dots_segment_cannot_escape_the_root(self, tmp_path: Path) -> None:
        written = place(_doc(host=".."), root=tmp_path)

        assert tmp_path in written.parents

    @pytest.mark.parametrize("field", ["repo", "host", "head_sha"])
    def test_an_empty_identity_field_is_refused(self, field: str) -> None:
        document = _doc()
        document["identity"][field] = ""

        with pytest.raises(MalformedDocument, match=field):
            relative_path(document)

    def test_an_unknown_schema_version_is_refused(self) -> None:
        document = _doc()
        document["schema_version"] = 99

        with pytest.raises(MalformedDocument, match="99"):
            relative_path(document)

    def test_a_foreign_document_is_refused(self) -> None:
        document = _doc()
        document["kind"] = "something.else"

        with pytest.raises(MalformedDocument, match="something.else"):
            relative_path(document)


class TestTheSinkIsAppendOnly:
    def test_placing_twice_refuses_rather_than_overwrites(self, tmp_path: Path) -> None:
        place(_doc(), root=tmp_path)

        with pytest.raises(FileExistsError):
            place(_doc(), root=tmp_path)

    def test_a_later_reading_does_not_replace_an_earlier_one(
        self, tmp_path: Path
    ) -> None:
        place(_doc(emitted_at="2026-09-01T12:00:00+00:00"), root=tmp_path)
        place(_doc(emitted_at="2026-09-01T18:00:00+00:00"), root=tmp_path)

        assert len(list(tmp_path.rglob("*.json"))) == 2


class TestWhichFactoryIsDegradingAndSinceWhen:
    def _tree(self, tmp_path: Path, docs: list[dict]) -> Path:
        for document in docs:
            place(document, root=tmp_path)
        return tmp_path

    def test_a_risen_ratchet_is_reported(self, tmp_path: Path) -> None:
        root = self._tree(
            tmp_path,
            [
                _doc(emitted_at="2026-09-01T00:00:00+00:00", **{"entries.count": 10}),
                _doc(emitted_at="2026-09-02T00:00:00+00:00", **{"entries.count": 12}),
            ],
        )

        found = regressions(read_tree(root))

        assert [(r.metric, r.was, r.now) for r in found] == [
            ("suppressions.entries.count", 10.0, 12.0)
        ]

    def test_since_is_when_it_first_rose_not_the_latest_reading(
        self, tmp_path: Path
    ) -> None:
        """ "Since when" must not answer "just now" for a week-old regression."""
        root = self._tree(
            tmp_path,
            [
                _doc(emitted_at="2026-09-01T00:00:00+00:00", **{"entries.count": 10}),
                _doc(emitted_at="2026-09-02T00:00:00+00:00", **{"entries.count": 12}),
                _doc(emitted_at="2026-09-03T00:00:00+00:00", **{"entries.count": 12}),
            ],
        )

        assert regressions(read_tree(root))[0].since == "2026-09-02T00:00:00+00:00"

    def test_a_shrinking_ratchet_is_not_a_regression(self, tmp_path: Path) -> None:
        root = self._tree(
            tmp_path,
            [
                _doc(emitted_at="2026-09-01T00:00:00+00:00", **{"entries.count": 12}),
                _doc(emitted_at="2026-09-02T00:00:00+00:00", **{"entries.count": 9}),
            ],
        )

        assert regressions(read_tree(root)) == ()

    def test_hosts_are_compared_against_themselves_not_each_other(
        self, tmp_path: Path
    ) -> None:
        """Two factories at different numbers are two facts, not a regression."""
        root = self._tree(
            tmp_path,
            [
                _doc(host="box-1", **{"entries.count": 10}),
                _doc(host="box-2", **{"entries.count": 900}),
            ],
        )

        assert regressions(read_tree(root)) == ()

    def test_one_reading_is_never_degrading(self, tmp_path: Path) -> None:
        """A newly-added factory must not look broken on its first emission."""
        root = self._tree(tmp_path, [_doc(**{"entries.count": 10})])

        assert regressions(read_tree(root)) == ()

    def test_the_degrading_host_is_named_among_healthy_ones(
        self, tmp_path: Path
    ) -> None:
        root = self._tree(
            tmp_path,
            [
                _doc(
                    host="ok",
                    emitted_at="2026-09-01T00:00:00+00:00",
                    **{"entries.count": 10},
                ),
                _doc(
                    host="ok",
                    emitted_at="2026-09-02T00:00:00+00:00",
                    **{"entries.count": 10},
                ),
                _doc(
                    host="bad",
                    emitted_at="2026-09-01T00:00:00+00:00",
                    **{"entries.count": 10},
                ),
                _doc(
                    host="bad",
                    emitted_at="2026-09-02T00:00:00+00:00",
                    **{"entries.count": 40},
                ),
            ],
        )

        found = regressions(read_tree(root))

        assert [r.host for r in found] == ["bad"]

    def test_a_truncated_upload_does_not_hide_every_other_factory(
        self, tmp_path: Path
    ) -> None:
        """A partial object-store sync is ordinary; one bad file is not fatal."""
        root = self._tree(
            tmp_path,
            [
                _doc(emitted_at="2026-09-01T00:00:00+00:00", **{"entries.count": 10}),
                _doc(emitted_at="2026-09-02T00:00:00+00:00", **{"entries.count": 12}),
            ],
        )
        (root / "repo=acme_hydraflow" / "truncated.json").write_text("{not json")

        assert len(regressions(read_tree(root))) == 1

    def test_an_empty_tree_says_so_rather_than_claiming_health(
        self, tmp_path: Path
    ) -> None:
        """The all-clear now answers BOTH questions.

        "No factory is degrading" alone was the sentence a dead fleet produces,
        which is why silence became its own reported fact (#11690 AC4).
        """
        assert report(tmp_path) == "no factory is degrading; none has gone quiet"

    def test_the_report_names_the_metric_and_when(self, tmp_path: Path) -> None:
        root = self._tree(
            tmp_path,
            [
                _doc(emitted_at="2026-09-01T00:00:00+00:00", **{"entries.count": 10}),
                _doc(emitted_at="2026-09-02T00:00:00+00:00", **{"entries.count": 12}),
            ],
        )

        text = report(root)

        assert "suppressions.entries.count" in text
        assert "since 2026-09-02T00:00:00+00:00" in text


class TestSilenceDoesNotReadAsHealth:
    """#11690 AC4: a factory that stops emitting is detectable as ABSENT.

    A degradation report over a tree that stopped being written says "no
    factory is degrading" — true of the data, and exactly wrong about the
    world. Absence has to be its own reported fact, not inferred from the lack
    of a finding.
    """

    _NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

    def _tree(self, tmp_path: Path, docs: list[dict]) -> Path:
        for document in docs:
            place(document, root=tmp_path)
        return tmp_path

    def test_a_factory_past_the_floor_is_reported_silent(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path, [_doc(emitted_at="2026-09-01T00:00:00+00:00")])

        quiet = silent(read_tree(root), now=self._NOW, floor_seconds=86_400)

        assert [(s.repo, s.host) for s in quiet] == [("acme/hydraflow", "box-1")]

    def test_a_recent_factory_is_not_silent(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path, [_doc(emitted_at="2026-09-03T11:00:00+00:00")])

        assert silent(read_tree(root), now=self._NOW, floor_seconds=86_400) == ()

    def test_one_host_going_quiet_is_seen_beside_a_live_one(
        self, tmp_path: Path
    ) -> None:
        """The case that matters: a fleet where only one has died."""
        root = self._tree(
            tmp_path,
            [
                _doc(host="live", emitted_at="2026-09-03T11:00:00+00:00"),
                _doc(host="dead", emitted_at="2026-09-01T00:00:00+00:00"),
            ],
        )

        quiet = silent(read_tree(root), now=self._NOW, floor_seconds=86_400)

        assert [s.host for s in quiet] == ["dead"]

    def test_the_newest_reading_decides_not_the_oldest(self, tmp_path: Path) -> None:
        """A long history must not make a currently-live factory look dead."""
        root = self._tree(
            tmp_path,
            [
                _doc(emitted_at="2026-08-01T00:00:00+00:00"),
                _doc(emitted_at="2026-09-03T11:00:00+00:00"),
            ],
        )

        assert silent(read_tree(root), now=self._NOW, floor_seconds=86_400) == ()

    def test_the_report_names_a_silent_factory_when_nothing_is_degrading(
        self, tmp_path: Path
    ) -> None:
        """The headline: a healthy-looking report over a dead fleet."""
        root = self._tree(tmp_path, [_doc(emitted_at="2026-09-01T00:00:00+00:00")])

        text = report(root, now=self._NOW, floor_seconds=86_400)

        assert "silent:" in text
        assert "box-1" in text
        assert text != "no factory is degrading"

    def test_an_all_clear_says_both_things(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path, [_doc(emitted_at="2026-09-03T11:00:00+00:00")])

        assert report(root, now=self._NOW, floor_seconds=86_400) == (
            "no factory is degrading; none has gone quiet"
        )


class TestTheSinkCarriesNoConformanceClaim:
    """#11690 AC5: losing the sink must lose vitals only.

    The emitter is deliberately a VITALS emitter — it says what the counters
    read, never that a gate holds. A sink that inferred compliance would make a
    conformance claim auditable only through a data plane's uptime, which
    #11688 rules out.
    """

    def test_no_module_here_renders_a_verdict(self) -> None:
        from vitals_sink import degrading, layout

        for module in (degrading, layout):
            source = Path(module.__file__).read_text(encoding="utf-8")
            names = {
                node.name
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.FunctionDef | ast.ClassDef)
            }
            offenders = {
                n
                for n in names
                if any(w in n.lower() for w in ("conform", "complian", "verdict"))
            }
            assert not offenders, (
                f"{module.__name__} exposes {offenders}; the sink reports what "
                f"the counters read, never whether a gate holds (#11688)"
            )
