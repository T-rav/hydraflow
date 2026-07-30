"""Signature classifier for post-merge full-machine smoke (s82) docker-build
infra flakes (#10776).

The post-merge smoke (``.github/workflows/ci.yml`` job ``post-merge-smoke``)
boots the real server once and drives both merge lanes on every push to
``staging``/``main``. Its first step is a ``docker compose … build`` of the
sandbox images, and that build reaches out to package CDNs (NodeSource,
GitHub CLI, astral.sh, npm registry, Debian/Ubuntu apt). Those CDNs
intermittently 403 / 5xx, and the Debian ``nodejs`` fallback ships without
``npm`` (so a later ``npm install -g`` dies with exit 127). When any of these
hit, the smoke goes red, files the rolling *"Post-merge smoke failing on …"*
``hydraflow-find`` issue, and a **human diagnoses the docker layer by hand** —
which happened twice in the 2026-07-27 break/fix cycle (#10740 NodeSource 403,
#10756 Debian-nodejs-missing-npm).

This module is the missing recognition step: a pure, well-tested classifier
that recognises those known infra-flake SIGNATURES in a build/smoke log and a
decision function that turns a recognised flake into (a) an *infra-transient*
verdict that the build should auto-retry ONCE before filing anything, and
(b), if it recurs after the retry, a TARGETED issue that names the specific
flaky dependency/step instead of the generic "smoke failed". A log that does
NOT match any signature is a real red and files normally.

Wiring note (recursion guard — ADR-0044 / ADR-0050)
---------------------------------------------------
The auto-agent / factory is, by the ADR-0050 pre-flight tool contract,
**forbidden from modifying any file under ``.github/workflows/``** (the
recursion guard: an agent must not edit the system that judges it). So the
classifier lives here in ``src/`` as a pure function with a thin CLI
(``scripts/classify_smoke_log.py``); the one-line workflow change that
consumes it is described below for an operator to apply by hand.

In ``.github/workflows/ci.yml``, job ``post-merge-smoke``, split the current
single build+run+file steps so the disposition drives them::

    - name: Build sandbox images
      id: build
      run: docker compose -f docker-compose.sandbox.yml build hydraflow ui playwright 2>&1 | tee /tmp/smoke-build.log
    # ... run s82 (make post-merge-smoke), teeing to /tmp/smoke-run.log ...
    - name: Classify + auto-retry infra flakes
      if: failure()
      id: classify
      run: |
        cat /tmp/smoke-build.log /tmp/smoke-run.log > /tmp/smoke.log 2>/dev/null || true
        python scripts/classify_smoke_log.py \
          --log /tmp/smoke.log \
          --prior-attempts "${SMOKE_PRIOR_ATTEMPTS:-0}" \
          --out "$GITHUB_OUTPUT"
      env:
        SMOKE_PRIOR_ATTEMPTS: ${{ github.run_attempt }}  # 1 on first run
    # On action == "retry": re-run the build+run once (a workflow re-run, or a
    #   bounded in-job retry loop). On action == "file_targeted": `gh issue
    #   create` with steps.classify.outputs.issue_title / issue_body. On
    #   action == "file_generic": keep today's rolling-issue block unchanged.

Only the YAML wiring is off-limits to the agent; this module and its CLI are
the reusable, tested core the wiring calls into.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "MAX_INFRA_RETRIES",
    "SIGNATURES",
    "InfraFlakeMatch",
    "InfraFlakeSignature",
    "SmokeAction",
    "SmokeDisposition",
    "classify_infra_flake",
    "decide_smoke_disposition",
]

# One auto-retry before we file anything. A genuine transient CDN blip clears
# on a single re-run; a signature that survives the retry is a standing outage
# worth a targeted issue rather than another silent retry.
MAX_INFRA_RETRIES = 1


@dataclass(frozen=True)
class InfraFlakeSignature:
    """One recognised docker-build/smoke infra-flake signature.

    ``pattern`` is matched (case-insensitive, multi-line, line-anchored)
    against the whole log; the matched line becomes the issue's evidence.
    ``dependency`` is the human-facing name of the flaky dependency/step that
    a targeted issue titles itself after. When ``dependency_group`` names a
    capture group present in the match, the captured token (e.g. the apt
    package name or the CDN host) refines the dependency so the filed issue is
    specific rather than generic.
    """

    id: str
    dependency: str
    pattern: re.Pattern[str]
    hint: str
    dependency_group: str | None = None


@dataclass(frozen=True)
class InfraFlakeMatch:
    """The strongest signature that matched a log, plus its evidence line."""

    signature_id: str
    dependency: str
    hint: str
    evidence: str


SmokeAction = Literal["retry", "file_targeted", "file_generic"]


@dataclass(frozen=True)
class SmokeDisposition:
    """What the post-merge-smoke failure step should do with one red.

    * ``retry`` — recognised infra flake, still within the retry budget: the
      build should re-run once before anything is filed.
    * ``file_targeted`` — recognised infra flake that recurred after the
      retry: file an issue named after ``dependency``.
    * ``file_generic`` — no known infra signature (a real red): file/append
      the rolling generic issue exactly as today.
    """

    action: SmokeAction
    signature_id: str | None = None
    dependency: str | None = None
    issue_title: str | None = None
    issue_body: str | None = None


# Known package/CDN infra hosts a build reaches during image assembly. Kept
# deliberately narrow — bare ``github.com`` is EXCLUDED so an application test
# that asserts an HTTP 500/503 against github.com can never be misread as a
# CDN infra flake. Only hosts that appear in `apt`/`curl`/`npm` fetch lines,
# never in product-code test output, belong here.
_CDN_HOSTS = (
    r"deb\.nodesource\.com",
    r"cli\.github\.com",
    r"astral\.sh",
    r"registry\.npmjs\.org",
    r"deb\.debian\.org",
    r"[\w.-]*\.ubuntu\.com",
    r"ghcr\.io",
    r"objects\.githubusercontent\.com",
    r"production\.cloudflare\.docker\.com",
    r"download\.docker\.com",
)
_CDN_HOST_ALT = "|".join(_CDN_HOSTS)

# Order is priority: the first signature whose pattern matches wins, so the
# most specific signatures precede the generic CDN-5xx catch-all.
SIGNATURES: tuple[InfraFlakeSignature, ...] = (
    InfraFlakeSignature(
        id="nodesource-cdn-403",
        dependency="NodeSource CDN (deb.nodesource.com)",
        # A line naming NodeSource AND carrying a 403 — the setup-script fetch
        # or its apt repo returning Forbidden (#10740). Order-independent via
        # two lookaheads so it fires whether the host or the code comes first.
        pattern=re.compile(
            r"(?im)^(?=.*nodesource)(?=.*\b403\b).*$",
        ),
        hint=(
            "NodeSource CDN returned 403. The Dockerfile already retries the "
            "setup-script fetch with backoff and guarantees npm from Debian on "
            "fallback (#10742/#10769); a recurrence means the CDN is out for "
            "longer than the retry window — pin a Node apt mirror or a "
            "prebuilt base image rather than re-fetching setup_20.x."
        ),
    ),
    InfraFlakeSignature(
        id="npm-exit-127",
        dependency="npm (exit 127 — nodejs installed without npm)",
        # `npm: not found` OR any line naming npm alongside exit-code 127. This
        # is the Debian-nodejs-missing-npm class (#10756): `apt-get install
        # nodejs` provides no npm, so `npm install -g …` dies with 127.
        pattern=re.compile(
            r"(?im)^(?:"
            r".*npm:\s*(?:command\s+)?not found.*"
            r"|(?=.*\bnpm\b)(?=.*\b127\b).*"
            r")$",
        ),
        hint=(
            "npm was missing (exit 127) — Debian's `nodejs` package ships "
            "without npm. The Dockerfile now installs npm explicitly on the "
            "fallback path and verifies `node`+`npm` (#10769); a recurrence "
            "means the guarantee step itself regressed — check the "
            "`command -v npm || apt-get install -y npm` guard in Dockerfile.agent-base."
        ),
    ),
    InfraFlakeSignature(
        id="apt-unable-to-locate-package",
        dependency="apt package",
        # apt could not find a package in its (stale/unreachable) index.
        pattern=re.compile(
            r"(?im)^.*unable to locate package\s+(?P<pkg>[\w.+-]+).*$",
        ),
        hint=(
            "apt could not locate a package — usually a stale or unreachable "
            "package index (the apt mirror 5xx'd, or `apt-get update` was "
            "skipped). Ensure `apt-get update` precedes the install and the "
            "mirror is reachable."
        ),
        dependency_group="pkg",
    ),
    InfraFlakeSignature(
        id="cdn-5xx",
        dependency="package CDN",
        # A known package/CDN host returning a 5xx on the same log line.
        pattern=re.compile(
            r"(?im)^(?=.*\b(?:500|502|503|504)\b)"
            rf"(?=.*(?P<host>{_CDN_HOST_ALT})).*$",
        ),
        hint=(
            "A package CDN returned a 5xx (transient outage). Retry usually "
            "clears it; a persistent 5xx from one host means that mirror is "
            "down — switch mirrors or pin the dependency into the base image."
        ),
        dependency_group="host",
    ),
)


def classify_infra_flake(log_text: str) -> InfraFlakeMatch | None:
    """Return the strongest infra-flake signature in *log_text*, or ``None``.

    Pure. Iterates :data:`SIGNATURES` in priority order and returns the first
    match, refining ``dependency`` with the signature's capture group when it
    names a specific package or host. ``None`` means no known infra signature
    was found — i.e. a real (non-infra) failure that must file normally.
    """
    if not log_text:
        return None
    for sig in SIGNATURES:
        match = sig.pattern.search(log_text)
        if match is None:
            continue
        dependency = sig.dependency
        if sig.dependency_group:
            captured = match.groupdict().get(sig.dependency_group)
            if captured:
                dependency = f"{sig.dependency} `{captured}`"
        return InfraFlakeMatch(
            signature_id=sig.id,
            dependency=dependency,
            hint=sig.hint,
            evidence=match.group(0).strip(),
        )
    return None


def _targeted_issue(
    match: InfraFlakeMatch,
    *,
    ref_name: str,
    sha: str,
    run_url: str,
) -> tuple[str, str]:
    """Build the (title, body) for a recurring-infra-flake targeted issue."""
    title = f"Post-merge smoke infra-flake: {match.dependency} on {ref_name}"
    body = (
        f"Post-merge full-machine smoke (s82) went red on `{ref_name}` at "
        f"{sha} with a recognised **infra-flake signature** "
        f"(`{match.signature_id}`) that survived the one automatic retry — so "
        f"this is a standing outage of a specific dependency, not a code "
        f"regression.\n\n"
        f"**Flaky dependency/step:** {match.dependency}\n\n"
        f"**Matched log line:**\n\n```\n{match.evidence}\n```\n\n"
        f"**Suggested fix:** {match.hint}\n\n"
        f"Run: {run_url}\n\n"
        f"_Filed automatically by the smoke infra-flake classifier "
        f"(#10776) after {MAX_INFRA_RETRIES} auto-retry did not clear it._"
    )
    return title, body


def decide_smoke_disposition(
    log_text: str,
    *,
    ref_name: str = "",
    sha: str = "",
    run_url: str = "",
    prior_attempts: int = 0,
) -> SmokeDisposition:
    """Decide what a post-merge-smoke failure step should do with one red.

    * A recognised infra flake within the retry budget
      (``prior_attempts < MAX_INFRA_RETRIES``) → ``retry`` (infra-transient:
      auto-retry once before filing).
    * A recognised infra flake that recurred (retry budget spent) →
      ``file_targeted`` with an issue that names the specific flaky
      dependency/step.
    * No recognised signature (a real red) → ``file_generic`` — the rolling
      "Post-merge smoke failing on …" issue files exactly as today.

    ``prior_attempts`` is the number of times this same push already ran and
    failed (e.g. GitHub's ``github.run_attempt`` minus one, or a counter the
    workflow threads through). Pure.
    """
    match = classify_infra_flake(log_text)
    if match is None:
        return SmokeDisposition(action="file_generic")
    if prior_attempts < MAX_INFRA_RETRIES:
        return SmokeDisposition(
            action="retry",
            signature_id=match.signature_id,
            dependency=match.dependency,
        )
    title, body = _targeted_issue(match, ref_name=ref_name, sha=sha, run_url=run_url)
    return SmokeDisposition(
        action="file_targeted",
        signature_id=match.signature_id,
        dependency=match.dependency,
        issue_title=title,
        issue_body=body,
    )
