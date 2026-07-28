"""Unit tests for the post-merge-smoke infra-flake classifier (#10776).

Signatures are exercised over realistic captured docker-build/smoke log
snippets (NodeSource 403, npm exit-127, apt unable-to-locate, CDN 5xx) plus
the load-bearing negative: a genuine test failure must NEVER classify as an
infra flake.
"""

from __future__ import annotations

from smoke_infra_flake import (
    MAX_INFRA_RETRIES,
    classify_infra_flake,
    decide_smoke_disposition,
)

# --------------------------------------------------------------------------
# Real captured log snippets
# --------------------------------------------------------------------------

# #10740 — NodeSource CDN 403 on the setup-script fetch and its apt repo.
NODESOURCE_403_LOG = """\
#8 [tools 5/9] RUN for i in 1 2 3; do curl -fsSL https://deb.nodesource.com/setup_20.x -o /tmp/nodesource_setup.sh && break; ...
#8 12.34 NodeSource fetch attempt 1 failed (CDN 403/5xx); retrying in 5s
#8 17.61 NodeSource fetch attempt 2 failed (CDN 403/5xx); retrying in 10s
#8 25.02 curl: (22) The requested URL returned error: 403
#8 25.44 W: Failed to fetch https://deb.nodesource.com/node_20.x/dists/nodistro/InRelease  403  Forbidden
#8 ERROR: process "/bin/sh -c ..." did not complete successfully: exit code: 1
"""

# #10756 — Debian's nodejs shipped without npm, so `npm install -g` exit 127.
NPM_127_LOG = """\
#12 [tools 8/9] RUN npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli --no-fund --no-audit
#12 0.402 /bin/sh: 1: npm: not found
#12 ERROR: process "/bin/sh -c npm install -g @anthropic-ai/claude-code @openai/codex --no-fund --no-audit" did not complete successfully: exit code: 127
"""

# Classic (non-buildkit) exit-127 rendering.
NPM_127_CLASSIC_LOG = """\
Step 8/12 : RUN npm install -g @beads/bd@1.0.4 --no-fund --no-audit
 ---> Running in a1b2c3d4e5f6
/bin/sh: npm: command not found
The command '/bin/sh -c npm install -g @beads/bd@1.0.4 --no-fund --no-audit' returned a non-zero code: 127
"""

# apt could not find a package (stale/unreachable index).
APT_UNABLE_TO_LOCATE_LOG = """\
#6 3.11 Reading package lists...
#6 3.98 Building dependency tree...
#6 4.02 E: Unable to locate package npm
#6 ERROR: process "/bin/sh -c apt-get install -y npm" did not complete successfully: exit code: 100
"""

# A different CDN (GitHub CLI apt repo) returning a 5xx.
CDN_5XX_LOG = """\
#9 1.10 RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg ...
#9 1.23 curl: (22) The requested URL returned error: 503
#9 1.24 W: Failed to fetch https://cli.github.com/packages/dists/stable/InRelease  503  Service Unavailable
"""

# astral.sh (uv installer) 502.
ASTRAL_5XX_LOG = """\
#7 0.88 RUN curl -LsSf https://astral.sh/uv/install.sh | sh
#7 1.44 curl: (56) OpenSSL SSL_read: error, https://astral.sh/uv/install.sh returned 502 Bad Gateway
"""

# The load-bearing NEGATIVE: a genuine test failure — no infra signature.
GENUINE_TEST_FAILURE_LOG = """\
============================= test session starts ==============================
FAILED tests/test_orchestrator.py::test_loop_starts - AssertionError: assert 3 == 4
FAILED tests/test_merge_policy.py::test_gate_blocks - assert response.status_code == 500
======================== 2 failed, 1893 passed in 63.11s =======================
make: *** [Makefile:88: post-merge-smoke] Error 1
"""

# A genuine failure that happens to mention github.com + 500 and an exit 127
# in application context — must STILL not classify (bare github.com is not a
# CDN host; the 127 is not on an npm line).
GENUINE_FAILURE_WITH_DECOY_TOKENS_LOG = """\
FAILED tests/test_webhook.py::test_retry - assert client.get("https://github.com/x").status_code != 500
FAILED tests/test_shell.py::test_exit - assert result.returncode == 127
======================== 2 failed, 40 passed in 4.20s ==========================
"""


class TestClassifyNodeSource403:
    def test_nodesource_403_is_recognised(self) -> None:
        match = classify_infra_flake(NODESOURCE_403_LOG)
        assert match is not None
        assert match.signature_id == "nodesource-cdn-403"

    def test_dependency_names_nodesource(self) -> None:
        match = classify_infra_flake(NODESOURCE_403_LOG)
        assert match is not None
        assert "NodeSource" in match.dependency

    def test_evidence_is_the_matched_line(self) -> None:
        match = classify_infra_flake(NODESOURCE_403_LOG)
        assert match is not None
        assert "403" in match.evidence
        assert "nodesource" in match.evidence.lower()


class TestClassifyNpm127:
    def test_buildkit_npm_not_found_is_recognised(self) -> None:
        match = classify_infra_flake(NPM_127_LOG)
        assert match is not None
        assert match.signature_id == "npm-exit-127"

    def test_classic_npm_command_not_found_is_recognised(self) -> None:
        match = classify_infra_flake(NPM_127_CLASSIC_LOG)
        assert match is not None
        assert match.signature_id == "npm-exit-127"

    def test_dependency_names_npm(self) -> None:
        match = classify_infra_flake(NPM_127_LOG)
        assert match is not None
        assert "npm" in match.dependency.lower()


class TestClassifyAptUnableToLocate:
    def test_unable_to_locate_is_recognised(self) -> None:
        match = classify_infra_flake(APT_UNABLE_TO_LOCATE_LOG)
        assert match is not None
        assert match.signature_id == "apt-unable-to-locate-package"

    def test_dependency_names_the_missing_package(self) -> None:
        match = classify_infra_flake(APT_UNABLE_TO_LOCATE_LOG)
        assert match is not None
        assert "npm" in match.dependency  # captured package name


class TestClassifyCdn5xx:
    def test_github_cli_503_is_recognised(self) -> None:
        match = classify_infra_flake(CDN_5XX_LOG)
        assert match is not None
        assert match.signature_id == "cdn-5xx"

    def test_dependency_names_the_host(self) -> None:
        match = classify_infra_flake(CDN_5XX_LOG)
        assert match is not None
        assert "cli.github.com" in match.dependency

    def test_astral_502_is_recognised(self) -> None:
        match = classify_infra_flake(ASTRAL_5XX_LOG)
        assert match is not None
        assert match.signature_id == "cdn-5xx"
        assert "astral.sh" in match.dependency


class TestGenuineFailuresAreNotInfra:
    def test_genuine_test_failure_is_not_classified(self) -> None:
        assert classify_infra_flake(GENUINE_TEST_FAILURE_LOG) is None

    def test_decoy_tokens_do_not_trigger_misclassification(self) -> None:
        # github.com+500 and a bare exit-127 in app context must NOT match.
        assert classify_infra_flake(GENUINE_FAILURE_WITH_DECOY_TOKENS_LOG) is None

    def test_empty_log_is_not_infra(self) -> None:
        assert classify_infra_flake("") is None


class TestSignaturePrecedence:
    def test_nodesource_403_wins_over_generic_cdn(self) -> None:
        # A NodeSource line carrying a 403 must classify as the specific
        # nodesource signature, not the generic CDN catch-all.
        match = classify_infra_flake(NODESOURCE_403_LOG)
        assert match is not None
        assert match.signature_id == "nodesource-cdn-403"


class TestDecideSmokeDisposition:
    def test_infra_flake_first_failure_retries(self) -> None:
        disp = decide_smoke_disposition(NODESOURCE_403_LOG, prior_attempts=0)
        assert disp.action == "retry"
        assert disp.signature_id == "nodesource-cdn-403"
        assert disp.issue_title is None

    def test_infra_flake_recurrence_files_targeted(self) -> None:
        disp = decide_smoke_disposition(
            NODESOURCE_403_LOG,
            ref_name="staging",
            sha="abc123",
            run_url="https://ci/run/1",
            prior_attempts=MAX_INFRA_RETRIES,
        )
        assert disp.action == "file_targeted"
        assert disp.issue_title is not None
        assert "NodeSource" in disp.issue_title
        assert "staging" in disp.issue_title

    def test_targeted_body_carries_evidence_hint_and_context(self) -> None:
        disp = decide_smoke_disposition(
            NPM_127_LOG,
            ref_name="staging",
            sha="deadbeef",
            run_url="https://ci/run/9",
            prior_attempts=1,
        )
        assert disp.issue_body is not None
        assert "deadbeef" in disp.issue_body
        assert "https://ci/run/9" in disp.issue_body
        assert "npm" in disp.issue_body.lower()
        # The remediation hint is included.
        assert "Debian" in disp.issue_body

    def test_real_red_files_generic(self) -> None:
        disp = decide_smoke_disposition(GENUINE_TEST_FAILURE_LOG, prior_attempts=0)
        assert disp.action == "file_generic"
        assert disp.signature_id is None
        assert disp.issue_title is None

    def test_real_red_files_generic_even_after_retries(self) -> None:
        # prior_attempts is irrelevant when there is no infra signature.
        disp = decide_smoke_disposition(GENUINE_TEST_FAILURE_LOG, prior_attempts=5)
        assert disp.action == "file_generic"

    def test_apt_targeted_issue_names_specific_package(self) -> None:
        disp = decide_smoke_disposition(
            APT_UNABLE_TO_LOCATE_LOG,
            ref_name="main",
            sha="f00",
            run_url="https://ci/run/2",
            prior_attempts=1,
        )
        assert disp.action == "file_targeted"
        assert disp.issue_title is not None
        assert "npm" in disp.issue_title
