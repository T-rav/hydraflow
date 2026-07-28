"""Regression #10740: NodeSource setup fetch must be retried, not single-shot.

The post-merge smoke (full-machine e2e, s82) went red on staging when the
agent docker image build hit ``curl: (22) The requested URL returned error:
403`` fetching ``https://deb.nodesource.com/setup_20.x``. The NodeSource CDN
intermittently 403s (and 5xxs); a bare ``curl -fsSL ... | bash -`` turns that
transient into a hard build failure — the setup script never runs, so the
following ``apt-get install nodejs`` can't locate the package and the whole
image build (hence the smoke, and the RC->main required Sandbox suite) fails.

These pins assert every agent Dockerfile wraps the NodeSource fetch in a retry
loop and never reintroduces the single-shot ``curl | bash`` form.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_DOCKERFILES = ("Dockerfile.agent", "Dockerfile.agent-base")
# The single-shot form that caused the outage: fetch piped straight to bash
# with no retry, so a transient CDN 403 is fatal.
_SINGLE_SHOT = "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -"


@pytest.mark.parametrize("dockerfile", _AGENT_DOCKERFILES)
def test_nodesource_fetch_is_retried(dockerfile: str) -> None:
    text = (_REPO_ROOT / dockerfile).read_text(encoding="utf-8")

    # It must still install Node via NodeSource...
    assert "deb.nodesource.com/setup_20.x" in text, (
        f"{dockerfile} no longer fetches the NodeSource setup script"
    )
    # ...but never as an un-retried single-shot pipe-to-bash.
    assert _SINGLE_SHOT not in text, (
        f"{dockerfile} reintroduced the single-shot `curl | bash` NodeSource "
        f"install; a transient CDN 403 will hard-fail the image build (#10740)"
    )
    # ...and the fetch must sit inside a retry loop.
    assert "for i in 1 2 3 4 5" in text, (
        f"{dockerfile} must wrap the NodeSource fetch in a retry loop so a "
        f"transient CDN 403/5xx does not fail the build (#10740)"
    )


@pytest.mark.parametrize("dockerfile", _AGENT_DOCKERFILES)
def test_npm_is_guaranteed_and_verified(dockerfile: str) -> None:
    """#10756: when the NodeSource *package* repo 403s, apt falls back to
    Debian's ``nodejs`` which ships no ``npm`` — so ``npm install -g`` later
    dies with exit 127. The build must guarantee npm regardless of which nodejs
    won, and verify both binaries so a half-install fails at THIS layer."""
    text = (_REPO_ROOT / dockerfile).read_text(encoding="utf-8")

    # npm must be ensured (installed as a fallback when the nodejs package that
    # won didn't bundle it).
    assert (
        "command -v npm" in text and "install -y --no-install-recommends npm" in text
    ), (
        f"{dockerfile} must guarantee npm is present after the nodejs install "
        f"(Debian's nodejs fallback ships no npm) — #10756"
    )
    # ...and both node and npm must be verified so a half-install fails loudly
    # here, not three build steps later at `npm install -g`.
    assert "node --version" in text and "npm --version" in text, (
        f"{dockerfile} must verify `node --version` AND `npm --version` so a "
        f"missing-npm install fails at this layer, not later (#10756)"
    )
