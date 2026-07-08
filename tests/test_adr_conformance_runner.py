from adr_conformance import CheckOutcome
from adr_index import Check
from mockworld.fakes.fake_conformance_runner import FakeConformanceRunner
from ports import ConformanceRunnerPort


def test_fake_satisfies_protocol_and_records_calls(tmp_path):
    runner: ConformanceRunnerPort = FakeConformanceRunner(
        {"make:arch-check": CheckOutcome.PASS}
    )
    res = runner.run(Check("make", "arch-check", "make:arch-check"), repo_root=tmp_path)
    assert res.outcome is CheckOutcome.PASS
    assert runner.calls == ["make:arch-check"]
