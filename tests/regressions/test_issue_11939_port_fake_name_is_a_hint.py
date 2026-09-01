"""#11939 — a Fake's NAME was taken as proof it satisfied the Port.

Upheld sampled re-audit of PR #11928. The extractor preferred a class named
``Fake<PortStem>`` and took the first match unconditionally, never checking it
had the Port's methods. The fallback scan below it *did* check — but only ran
when the name match failed.

So ``PRPort`` resolved to ``FakePR``, a PR **record** dataclass with zero public
methods, rather than ``FakeGitHub``, the actual adapter. That wrong pairing was
rendered into the generated port registry which
``docs/standards/ports-and-loops`` cites as the enforcer of "Every Port's Fake
satisfies the Protocol structurally, signature for signature" — so the standard
named a fake nothing had ever checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arch.extractors.ports import extract_ports

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"
_FAKES_DIR = _SRC_DIR / "mockworld" / "fakes"


def _fake_for(port_name: str) -> str | None:
    for info in extract_ports(src_dir=_SRC_DIR, fakes_dir=_FAKES_DIR):
        if info.name == port_name:
            return info.fake.name if info.fake else None
    raise AssertionError(f"{port_name} is not in the extracted registry")


def test_the_named_candidate_must_also_satisfy_the_port() -> None:
    # The exact instance: FakePR is a dataclass and wins on name alone.
    assert _fake_for("PRPort") == "FakeGitHub"


def _tiny_repo(tmp_path: Path, *, fakes: str) -> tuple[Path, Path]:
    """A two-file repo: one Port, and whatever Fakes the caller writes."""
    src = tmp_path / "src"
    fakes_dir = src / "fakes"
    fakes_dir.mkdir(parents=True)
    (src / "ports.py").write_text(
        "from typing import Protocol\n\n\n"
        "class ThingPort(Protocol):\n"
        "    def do_it(self, name: str) -> None: ...\n",
        encoding="utf-8",
    )
    (fakes_dir / "fakes.py").write_text(fakes, encoding="utf-8")
    return src, fakes_dir


#: Each case is a two-Fake repo where the two selection rules could disagree,
#: plus the one answer the extractor must give. Parametrised over the RULE
#: rather than written three times: they differ only in the Fakes on disk.
_SELECTION_CASES = (
    pytest.param(
        "class FakeAaaFirstAlphabetically:\n"
        "    def do_it(self, name: str) -> None: ...\n\n\n"
        "class FakeThing:\n"
        "    def do_it(self, name: str) -> None: ...\n",
        "FakeThing",
        id="the-conventional-name-wins-when-both-satisfy",
    ),
    pytest.param(
        "class FakeSomethingElse:\n    def do_it(self, name: str) -> None: ...\n",
        "FakeSomethingElse",
        id="the-scan-still-finds-an-unconventionally-named-adapter",
    ),
    pytest.param(
        "class FakeThing:\n"
        "    number: int = 0\n\n\n"
        "class FakeRealAdapter:\n"
        "    def do_it(self, name: str) -> None: ...\n",
        "FakeRealAdapter",
        id="the-right-name-with-none-of-the-methods-is-refused",
    ),
)


@pytest.mark.parametrize(("fakes", "expected"), _SELECTION_CASES)
def test_the_fake_is_chosen_by_name_then_proved_by_methods(
    tmp_path: Path, fakes: str, expected: str
) -> None:
    """All three branches of the selection, each with a case that shows it.

    Against the live repo only the third is observable: `FakeWorkspace` is both
    the name match and the only superset, so deleting the preference entirely
    changes nothing there and a mutation run proved that assertion vacuous.
    These build the disagreement instead of hoping the repo contains one — and
    the second matters as much as the first, since `PRPort`'s real adapter is
    `FakeGitHub`, a name the convention would never reach.
    """
    src, fakes_dir = _tiny_repo(tmp_path, fakes=fakes)

    (info,) = extract_ports(src_dir=src, fakes_dir=fakes_dir)

    assert info.fake is not None
    assert info.fake.name == expected


def test_every_live_port_resolves_to_a_fake() -> None:
    """A Port the extractor cannot pair drops out of every downstream check.

    `test_mockworld_fakes_conformance` derives its parametrization from this
    output, and it skips unpaired Ports — so an unresolvable Port silently
    narrows coverage instead of failing it, which is the shape of the original
    defect.
    """
    unpaired = [
        info.name
        for info in extract_ports(src_dir=_SRC_DIR, fakes_dir=_FAKES_DIR)
        if info.fake is None
    ]

    assert not unpaired, f"live Ports with no resolvable Fake: {unpaired}"


def test_the_extractor_still_finds_the_ports() -> None:
    """Anti-vacuity: every assertion above is silent on an empty registry."""
    assert len(extract_ports(src_dir=_SRC_DIR, fakes_dir=_FAKES_DIR)) >= 10
