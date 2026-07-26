"""Single-source-of-truth guard for the escape-ledger filename (#10578).

The ledger filename ``escape_ledger.jsonl`` was hardcoded independently in
``service_registry``, ``escape_ledger_loop``, ``sampled_audit_loop`` and
``vitals.observe`` — the cross-module duplication class the concept-scatter
sensor (#10104) flags for JSONL stores. It now has ONE public home,
``escape.ledger.ESCAPE_LEDGER_FILENAME``; every caller resolves the ledger
location through it. This test fails the moment a bare literal reappears at any
call site.
"""

from __future__ import annotations

import re
from pathlib import Path

from escape.ledger import ESCAPE_LEDGER_FILENAME

# The quoted literal (either quote style), NOT the backtick-wrapped docstring
# prose that legitimately names the file in module documentation.
_QUOTED_LITERAL = re.compile(r"""['"]escape_ledger\.jsonl['"]""")

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
_CALL_SITES = (
    "service_registry.py",
    "escape_ledger_loop.py",
    "sampled_audit_loop.py",
    "vitals/observe.py",
)


class TestEscapeLedgerFilenameConstant:
    def test_constant_holds_canonical_filename(self) -> None:
        assert ESCAPE_LEDGER_FILENAME == "escape_ledger.jsonl"

    def test_call_sites_carry_no_bare_filename_literal(self) -> None:
        offenders = {
            name: _QUOTED_LITERAL.findall((_SRC_DIR / name).read_text())
            for name in _CALL_SITES
        }
        offenders = {name: hits for name, hits in offenders.items() if hits}
        assert not offenders, (
            "escape_ledger.jsonl must resolve through "
            f"escape.ledger.ESCAPE_LEDGER_FILENAME, but bare literals remain: {offenders}"
        )

    def test_constant_is_the_only_quoted_definition_in_src(self) -> None:
        definitions = [
            path
            for path in _SRC_DIR.rglob("*.py")
            if _QUOTED_LITERAL.search(path.read_text())
        ]
        assert definitions == [_SRC_DIR / "escape" / "ledger.py"], (
            "the quoted escape_ledger.jsonl literal must live only in "
            f"escape/ledger.py, found in: {[str(p) for p in definitions]}"
        )
