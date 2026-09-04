"""#12142: `--only` must not raise a mark it was not asked to raise.

`regen_mass_baseline --only <key>` exists so a decomposition PR re-records
exactly the entry it shrank (#11646). It does that correctly BETWEEN entries and
cannot do it WITHIN one, because a class entry is a single mapping:

    src/config.py:HydraFlowConfig:
      loc: 5059
      methods: 45

Re-recording to capture a genuine `loc` shrink also re-records `methods` at
whatever it happens to be — including growth from other people's merges that no
PR ever accounted for. Measured on #12141: the PR added zero methods, yet the
refresh would have moved the mark 45 -> 50, and `loc` was stale by 1,075 lines
in the same entry. A shrink-only ratchet carrying that much unrecorded growth is
not enforcing shrink-only; it is a mark nothing had to clear.

No MockWorld scenario layer: `regen_mass_baseline` is an operator script run by
hand from a decomposition PR. It is not wired into any loop, no Port reaches it,
and nothing in the pipeline invokes it — a scenario would have to construct the
CLI and call `main()`, which is what the two CLI tests below already do against
a real baseline file on disk. The layer that would add coverage here is the CLI
test, and it is present.
"""

from __future__ import annotations

from erosion.mass_baseline import MassBaseline, laundered_metrics


def test_a_metric_that_rises_while_another_falls_is_reported() -> None:
    """The #12141 shape exactly: loc fell below its mark, methods climbed.

    The shrink was the errand; the climb was a passenger. Only the passenger is
    reported, because that is the number nobody reviewed.
    """
    recorded = MassBaseline(classes={"src/config.py:Cfg": {"loc": 5059, "methods": 45}})
    live = MassBaseline(classes={"src/config.py:Cfg": {"loc": 4983, "methods": 50}})

    grown = laundered_metrics(recorded, live, ["src/config.py:Cfg"])

    assert grown == {"src/config.py:Cfg": {"methods": (45, 50)}}


def test_a_pure_shrink_reports_nothing() -> None:
    """The mode this flag must not obstruct: everything moved the right way."""
    recorded = MassBaseline(classes={"src/config.py:Cfg": {"loc": 5059, "methods": 45}})
    live = MassBaseline(classes={"src/config.py:Cfg": {"loc": 4983, "methods": 44}})

    assert laundered_metrics(recorded, live, ["src/config.py:Cfg"]) == {}


def test_a_uniform_rise_is_the_accepted_growth_flow_and_is_not_blocked() -> None:
    """Both metrics up is the script's documented "accepted decision" mode.

    `regen_mass_baseline`'s own docstring says to rerun it "when a new oversized
    class is an accepted decision", and `refresh_entries` adopts a live entry
    that is not yet baselined. Refusing a uniform rise would break the mode this
    script exists to serve — which is exactly what the pre-existing contract
    test `test_targeted_regen_rewrites_only_the_named_entry` caught.
    """
    recorded = MassBaseline(classes={"src/hub.py:Hub": {"loc": 10, "methods": 41}})
    live = MassBaseline(classes={"src/hub.py:Hub": {"loc": 91, "methods": 45}})

    assert laundered_metrics(recorded, live, ["src/hub.py:Hub"]) == {}


def test_a_file_entry_can_never_launder() -> None:
    """A file entry records ONE number, so nothing can ride along beside it."""
    recorded = MassBaseline(files={"src/config.py": 7339})
    live = MassBaseline(files={"src/config.py": 7400})

    assert laundered_metrics(recorded, live, ["src/config.py"]) == {}


def test_only_the_named_keys_are_examined() -> None:
    """`--only` is a scope; growth elsewhere is not this refresh's business."""
    recorded = MassBaseline(
        classes={"a.py:A": {"loc": 10, "methods": 1}, "b.py:B": {"loc": 10, "methods": 1}}
    )
    live = MassBaseline(
        classes={"a.py:A": {"loc": 9, "methods": 1}, "b.py:B": {"loc": 99, "methods": 9}}
    )

    assert laundered_metrics(recorded, live, ["a.py:A"]) == {}


def test_an_unbaselined_key_being_adopted_reports_no_growth() -> None:
    """Adopting a genuinely new god class is not raising an existing mark."""
    recorded = MassBaseline()
    live = MassBaseline(classes={"new.py:N": {"loc": 900, "methods": 40}})

    assert laundered_metrics(recorded, live, ["new.py:N"]) == {}


def _stale_baseline(tmp_path, key: str, entry: dict[str, int]):
    """Write a baseline whose mark for *key* sits BELOW the live reading."""
    import yaml

    out = tmp_path / "mass.yaml"
    out.write_text(yaml.safe_dump({"files": {}, "classes": {key: entry}}))
    return out


def test_the_cli_refuses_a_refresh_that_would_raise_a_mark(tmp_path, capsys) -> None:
    """End-to-end: the operator is stopped and told which metric would rise."""
    import sys

    sys.path.insert(0, "scripts")
    from regen_mass_baseline import main

    # A real god class, recorded far below reality, so the live reading rises.
    # loc recorded absurdly high so it FALLS; methods recorded at 1 so it RISES.
    key = "src/config.py:HydraFlowConfig"
    out = _stale_baseline(tmp_path, key, {"loc": 999_999, "methods": 1})

    rc = main(["--only", key, "--reason", "test", "--out", str(out)])

    assert rc == 1, "a refresh that raises a mark must not succeed silently"
    err = capsys.readouterr().err
    assert "raise was not the errand" in err
    assert "methods: 1 ->" in err
    assert out.read_text().count("methods: 1") == 1, "baseline must be untouched"


def test_the_cli_allows_it_when_the_operator_says_so(tmp_path) -> None:
    """The escape hatch exists; it must actually write."""
    import sys

    sys.path.insert(0, "scripts")
    from regen_mass_baseline import main

    key = "src/config.py:HydraFlowConfig"
    out = _stale_baseline(tmp_path, key, {"loc": 999_999, "methods": 1})

    rc = main(
        ["--only", key, "--reason", "accounted for", "--out", str(out),
         "--allow-metric-growth"]
    )

    assert rc == 0
    assert "methods: 1\n" not in out.read_text(), "the mark should have moved"
