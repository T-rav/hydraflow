"""Regression guard for #10776 — smoke infra-flake classifier.

The post-merge full-machine smoke went red TWICE (#10740 NodeSource CDN 403,
#10756 Debian-nodejs-missing-npm exit 127) on docker-build INFRA flakes, and a
human diagnosed the docker layer by hand each time. The fix adds a signature
classifier (``src/smoke_infra_flake.py``) that recognises the known infra-flake
signatures, marks them infra-transient (auto-retry once), and files a TARGETED
issue on recurrence — while leaving real (non-infra) smoke reds to file
normally.

Two invariants must never regress:

1. **A genuine test failure must NEVER be classified as an infra flake.** If it
   were, a real code regression would be auto-retried and then filed as an
   "infra" issue, silently masking the bug the smoke exists to catch. This is
   the load-bearing negative — the whole feature is only safe if it never
   swallows a real red.
2. **A recognised infra flake retries first, then files a targeted issue** that
   names the specific flaky dependency — not the generic "smoke failed".
"""

from __future__ import annotations

from smoke_infra_flake import classify_infra_flake, decide_smoke_disposition

# A real regression the smoke caught — NOT infra. Contains decoy tokens (an
# HTTP 500 against github.com, a bare exit-127 in a shell test) that must not
# be mistaken for a CDN 5xx or an npm-127 infra flake.
GENUINE_RED_LOG = """\
============================= test session starts ==============================
FAILED tests/test_orchestrator.py::test_loop_wiring - AssertionError: assert 3 == 4
FAILED tests/test_webhook.py::test_retry - assert client.get("https://github.com/x").status_code != 500
FAILED tests/test_shell.py::test_exit_code - assert subprocess.run(...).returncode == 127
======================== 3 failed, 1893 passed in 63.11s =======================
make: *** [Makefile:88: post-merge-smoke] Error 1
"""

# #10740 NodeSource CDN 403 (real captured shape).
NODESOURCE_403_LOG = (
    "#8 12.34 NodeSource fetch attempt 3 failed (CDN 403/5xx); giving up\n"
    "#8 25.44 W: Failed to fetch https://deb.nodesource.com/node_20.x 403 Forbidden\n"
)

# #10756 Debian nodejs without npm -> `npm install -g` exit 127.
NPM_127_LOG = (
    "#12 0.402 /bin/sh: 1: npm: not found\n"
    '#12 ERROR: process "/bin/sh -c npm install -g @anthropic-ai/claude-code" '
    "did not complete successfully: exit code: 127\n"
)


def test_genuine_test_failure_is_never_infra() -> None:
    assert classify_infra_flake(GENUINE_RED_LOG) is None
    disp = decide_smoke_disposition(GENUINE_RED_LOG, prior_attempts=0)
    assert disp.action == "file_generic"
    # Even after retries a real red must keep filing generically, never as an
    # infra-transient retry that could mask the regression.
    assert decide_smoke_disposition(GENUINE_RED_LOG, prior_attempts=9).action == (
        "file_generic"
    )


def test_nodesource_403_retries_then_files_targeted() -> None:
    first = decide_smoke_disposition(NODESOURCE_403_LOG, prior_attempts=0)
    assert first.action == "retry"

    recurred = decide_smoke_disposition(
        NODESOURCE_403_LOG,
        ref_name="staging",
        sha="f836a52",
        run_url="https://ci/run/30302570096",
        prior_attempts=1,
    )
    assert recurred.action == "file_targeted"
    assert recurred.issue_title is not None
    assert "NodeSource" in recurred.issue_title


def test_npm_127_files_targeted_naming_npm() -> None:
    disp = decide_smoke_disposition(NPM_127_LOG, prior_attempts=1)
    assert disp.action == "file_targeted"
    assert disp.issue_title is not None
    assert "npm" in disp.issue_title.lower()
