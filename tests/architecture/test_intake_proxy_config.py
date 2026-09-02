"""The intake proxy's security properties live in nginx config, so test them.

`docker/hydraflow-proxy/templates/hydraflow.conf.template` is the only thing
facing the network on a remote deploy, and it carries decisions no Python test
would otherwise read:

* `source` is pinned per lane, so a caller cannot choose its own provenance.
  Triage auto-closes sensor issues that fail (`triage_phase._flow_route`), so a
  forged `source=bugsink` is a way to get a real report discarded.
* `/api/issues/intake` is not reachable directly, which is what makes the
  pinning above unavoidable rather than merely offered.
* Everything else 404s, because the dashboard has no in-process authentication
  on ~160 of its routes (ADR-0138 §D5).

Asserted per LOCATION BLOCK rather than over the whole file: a file-wide grep
for `set $args source=bugsink` passes just as happily when the line sits in the
wrong lane, which is the mistake worth catching.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "docker"
    / "hydraflow-proxy"
    / "templates"
    / "hydraflow.conf.template"
)

#: lane -> (path prefix, the source it must pin, its rate-limit zone)
LANES = {
    "exception": ("/exception/", "source=bugsink", "hf_exception"),
    "report": ("/report/", "source=ui", "hf_report"),
}


def _uncommented(text: str) -> str:
    """Config with comment lines removed.

    The template explains itself at length, and several of those sentences
    quote the very directives asserted below. Without this every check could be
    satisfied by prose describing the rule instead of the rule.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _location_blocks(text: str) -> dict[str, str]:
    """Map each ``location`` matcher to its block body, brace-balanced."""
    blocks: dict[str, str] = {}
    for match in re.finditer(r"location\s*(=?)\s*(\S+)\s*\{", text):
        matcher = match.group(2)
        depth, index = 1, match.end()
        while depth and index < len(text):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        blocks[matcher] = text[match.end() : index]
    return blocks


@pytest.fixture(scope="module")
def blocks() -> dict[str, str]:
    assert TEMPLATE.is_file(), f"proxy template missing: {TEMPLATE}"
    found = _location_blocks(_uncommented(TEMPLATE.read_text(encoding="utf-8")))
    assert found, "parsed no location blocks — the parser, not the config, broke"
    return found


def _lane_block(blocks: dict[str, str], prefix: str) -> str:
    matches = [body for matcher, body in blocks.items() if matcher.startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one {prefix} lane, got {len(matches)}"
    return matches[0]


class TestTheLanesArePinned:
    @pytest.mark.parametrize("lane", sorted(LANES))
    def test_each_lane_pins_its_own_source(self, blocks, lane: str) -> None:
        prefix, expected_source, _zone = LANES[lane]

        body = _lane_block(blocks, prefix)

        assert f"set $args {expected_source};" in body, (
            f"the {lane} lane must pin {expected_source} so the caller cannot "
            "choose its own provenance"
        )

    @pytest.mark.parametrize("lane", sorted(LANES))
    def test_no_lane_pins_another_lanes_source(self, blocks, lane: str) -> None:
        """The decoy: one block carrying both pins would satisfy the test above."""
        prefix, expected_source, _zone = LANES[lane]
        others = {src for _p, src, _z in LANES.values()} - {expected_source}

        body = _lane_block(blocks, prefix)

        for other in others:
            assert other not in body, f"{lane} lane must not also pin {other}"

    @pytest.mark.parametrize("lane", sorted(LANES))
    def test_each_lane_injects_the_operator_bearer(self, blocks, lane: str) -> None:
        prefix, _source, _zone = LANES[lane]

        body = _lane_block(blocks, prefix)

        assert 'proxy_set_header Authorization "Bearer' in body

    @pytest.mark.parametrize("lane", sorted(LANES))
    def test_each_lane_is_post_only(self, blocks, lane: str) -> None:
        prefix, _source, _zone = LANES[lane]

        body = _lane_block(blocks, prefix)

        assert "limit_except POST" in body and "deny all;" in body

    @pytest.mark.parametrize("lane", sorted(LANES))
    def test_each_lane_has_its_own_rate_limit_zone(self, blocks, lane: str) -> None:
        """Separate zones: an error storm must not starve the lane a person uses."""
        prefix, _source, zone = LANES[lane]

        body = _lane_block(blocks, prefix)

        assert f"limit_req zone={zone}" in body


class TestTheProxyPointsAtTheDashboard:
    """The upstream default must be the dashboard's port, not the backend's.

    These two live in different files — a compose default and a Pydantic field —
    and the first version of this compose pointed at 8000, which is *Bugsink's*
    port. The stack would have come up healthy with every intake failing.
    """

    def test_the_compose_default_upstream_is_the_dashboard_port(self) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        from config import HydraFlowConfig

        expected = HydraFlowConfig.model_fields["dashboard_port"].default
        compose_path = (
            Path(__file__).resolve().parents[2] / "docker-compose.intake-proxy.yml"
        )
        assert compose_path.is_file(), (
            f"{compose_path.name} missing — the proxy service moved and this "
            "guard would silently stop checking anything"
        )
        compose = compose_path.read_text(encoding="utf-8")

        match = re.search(r"HF_UPSTREAM:\s*\$\{HF_UPSTREAM:-([^}]+)\}", compose)

        assert match, "HF_UPSTREAM default not found in docker-compose.bugsink.yml"
        assert match.group(1).endswith(f":{expected}"), (
            f"proxy upstream {match.group(1)!r} does not point at the dashboard "
            f"port {expected} — the intake would fail against a healthy stack"
        )


class TestNothingElseIsReachable:
    def test_the_intake_is_not_exposed_directly(self, blocks) -> None:
        """Reaching it directly would mean choosing your own `source`."""
        assert not [m for m in blocks if "/api/" in m], (
            "no /api/ path may be a location: the lanes rewrite onto the intake, "
            f"they do not publish it. Found: {sorted(blocks)}"
        )

    def test_the_default_location_denies(self, blocks) -> None:
        assert "/" in blocks, "a default location must exist to deny with"
        assert "return 404;" in blocks["/"]

    def test_only_the_two_lanes_and_the_default_exist(self, blocks) -> None:
        """A third open location is a third thing to have reasoned about."""
        assert len(blocks) == len(LANES) + 1, f"unexpected locations: {sorted(blocks)}"
