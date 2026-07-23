"""Regression test for issues #9505 + #9465.

Bug: ``arch.extractors.adr_xref.extract_adr_refs`` appended one ``ADRRef`` per
ADR *file* with no merge. Two files sharing an ADR number (the #9406-style
collisions) therefore produced two ``ADRRef`` rows with the same ``adr_id``.
Every downstream consumer keys by ``adr_id`` (``{r.adr_id: r ...}`` and the
``adr_cross_reference`` generator's reverse-index build), so one file's
``cited_modules`` was silently dropped — the last row keyed wins.

Separately (#9465), unlike ``adr_index.scan_adr_directory``, the extractor
emitted *no* WARNING when it observed a duplicate ADR number, leaving the
collision invisible on the runtime path (mirrors the #9457 caplog pattern).

These tests assert the CORRECT (post-fix) invariant:
  * exactly ONE ``ADRRef`` per ``adr_id``, whose ``cited_modules`` is the
    de-duplicated UNION of every file claiming that number, and
  * a WARNING naming the colliding number is emitted.
"""

from __future__ import annotations

import logging
from pathlib import Path

from arch.extractors.adr_xref import extract_adr_refs


def _write_adr(adr_dir: Path, number: int, slug: str, body: str) -> Path:
    """Write an ADR file. ``slug`` keeps filenames distinct so two files can
    legitimately claim the same ADR ``number``."""
    p = adr_dir / f"{number:04d}-{slug}.md"
    p.write_text(f"# ADR-{number:04d}: {slug}\n\n{body}\n")
    return p


def test_duplicate_adr_number_merges_cited_modules_and_warns(tmp_path, caplog) -> None:
    # Two distinct files both claim ADR-0099, citing different src modules with
    # one module (src/shared.py) cited by BOTH — the union must de-dupe it.
    _write_adr(
        tmp_path,
        99,
        "first-decision",
        "See src/foo.py and src/shared.py:helper for details.",
    )
    _write_adr(
        tmp_path,
        99,
        "second-decision",
        "Also relies on src/bar.py:Bar and src/shared.py.",
    )
    _write_adr(tmp_path, 7, "unrelated", "Touches src/baz.py only.")

    with caplog.at_level(logging.WARNING):
        idx = extract_adr_refs(tmp_path)

    # Exactly ONE ADRRef per adr_id — the collision is merged, not duplicated.
    ids = [r.adr_id for r in idx.adr_to_modules]
    assert ids.count("ADR-0099") == 1, (
        f"Expected a single merged ADRRef for ADR-0099; got rows: {ids}"
    )

    by_id = {r.adr_id: r for r in idx.adr_to_modules}

    # cited_modules is the de-duplicated UNION of both files, sorted.
    assert by_id["ADR-0099"].cited_modules == [
        "src.bar",
        "src.foo",
        "src.shared",
    ], (
        "ADR-0099 must union both files' citations (shared module deduped); "
        f"got: {by_id['ADR-0099'].cited_modules}"
    )

    # The non-colliding ADR is unaffected.
    assert by_id["ADR-0007"].cited_modules == ["src.baz"]

    # #9465: a WARNING naming the colliding number MUST be emitted.
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "extract_adr_refs observed two files sharing ADR number 0099 but emitted "
        "no WARNING — duplicate ADR numbers stay invisible on the runtime path "
        "(mirror scan_adr_directory per #9457/#9465)."
    )
    assert any("99" in r.getMessage() for r in warnings), (
        "Expected a WARNING mentioning the duplicated ADR number 99; got: "
        f"{[r.getMessage() for r in warnings]}"
    )
