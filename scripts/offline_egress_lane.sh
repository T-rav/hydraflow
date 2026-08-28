#!/usr/bin/env bash
# Verify that this process tree has NO route off the host, then run a command
# inside it (#11706).
#
# The static half of the offline-conformance rule lives in
# tests/architecture/test_vitals_conformance_seam.py. It reads source, and
# docs/standards/vitals_conformance/README.md records what source cannot say:
# an orchestrator whose *configuration* reaches out (mkdocs' plugin list), a
# `git fetch` whose remote is configured elsewhere, an argv assembled from
# non-literals, a spawn performed by a helper the check calls. Every one of
# those is answered by observing the process instead of parsing it.
#
# This script does NOT create the isolation. It VERIFIES it and then runs. That
# split is deliberate:
#
#   * the mechanism differs per host — `unshare --net` on a CI runner, `docker
#     run --network none` on a laptop, a firewall rule on a fixed builder — and
#     a script that owned one of them could only ever be tested against one;
#   * a lane whose isolation silently stopped applying would go on passing,
#     which is the exact failure the standard it enforces is about. So the
#     canaries below run EVERY time, and a reachable network is a hard error
#     rather than a warning.
#
# Usage:
#   scripts/offline_egress_lane.sh --verify-only
#   scripts/offline_egress_lane.sh [--user UID:GID] -- <command> [args...]
#
# Typical CI invocation (the caller supplies the isolation):
#   sudo unshare --net -- scripts/offline_egress_lane.sh --user "$(id -u):$(id -g)" \
#     -- env PYTHONPATH=src HOME="$HOME" .venv/bin/python -m pytest tests/architecture
#
# Exit codes:
#   0  isolated, and the command succeeded
#   1  the command failed
#   3  NOT isolated — a canary reached the network, or loopback is broken
#   2  bad usage

set -euo pipefail

PROG="$(basename "$0")"

fail() {
  echo "$PROG: ERROR: $*" >&2
  exit "${EXIT_CODE:-3}"
}

usage() {
  sed -n '/^# Usage:/,/^# Exit codes:/p' "$0" >&2
}

VERIFY_ONLY=0
DROP_TO=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --verify-only) VERIFY_ONLY=1; shift ;;
    --user) DROP_TO="${2:-}"; shift 2 ;;
    --) shift; break ;;
    -h|--help) usage; exit 0 ;;
    *) EXIT_CODE=2 fail "unknown option: $1" ;;
  esac
done

if [ "$VERIFY_ONLY" -eq 0 ] && [ "$#" -eq 0 ]; then
  usage
  exit 2
fi

PYTHON_BIN="${HF_EGRESS_PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$candidate"; break; fi
  done
fi
[ -n "$PYTHON_BIN" ] || EXIT_CODE=3 fail "no python3 on PATH; the canaries cannot run, so isolation is unproven"

# `unshare --net` hands over a namespace whose loopback interface is DOWN. The
# conformance roots really do use loopback (measured: every connect they make
# is to 127.0.0.1), so leaving it down would redden the suite for a reason that
# has nothing to do with egress — the "silently degrades" failure pointing the
# other way.
if [ "$(id -u)" = "0" ] && command -v ip >/dev/null 2>&1; then
  ip link set lo up 2>/dev/null || true
fi

# --- the canaries -----------------------------------------------------------
# Three, and all three are load-bearing. Two prove egress is blocked; the third
# proves the block is egress and not "the network stack is gone", which would
# fail the suite for the wrong reason and teach everyone to switch the lane off.
CANARY_REPORT="$("$PYTHON_BIN" - <<'PY'
import socket
import sys

VERDICTS = []


def blocked(label, probe):
    try:
        probe()
    except OSError as exc:
        VERDICTS.append(("ok", f"{label}: blocked ({type(exc).__name__})"))
        return
    VERDICTS.append(("reached", f"{label}: REACHED"))


def direct_ip():
    # A public resolver, by address: no DNS, no proxy honoured, nothing cached.
    with socket.create_connection(("1.1.1.1", 443), timeout=5):
        pass


def dns():
    socket.getaddrinfo("github.com", 443)


blocked("outbound TCP to 1.1.1.1:443", direct_ip)
blocked("DNS lookup", dns)

try:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    with socket.create_connection(server.getsockname(), timeout=5):
        pass
    server.close()
    VERDICTS.append(("ok", "loopback connect: works"))
except OSError as exc:
    VERDICTS.append(("loopback", f"loopback connect: BROKEN ({exc})"))

for verdict, line in VERDICTS:
    print(f"{verdict}\t{line}")
sys.exit(0)
PY
)"

echo "$CANARY_REPORT" | while IFS=$'\t' read -r _ line; do echo "$PROG: canary: $line"; done

if echo "$CANARY_REPORT" | grep -q '^reached'; then
  fail "this process tree can still reach the network. The lane is not \
isolating anything, so a green run here would prove nothing. Wrap the command \
in a network namespace (\`sudo unshare --net -- $PROG ...\`) or a \
\`--network none\` container."
fi

if echo "$CANARY_REPORT" | grep -q '^loopback'; then
  fail "loopback is unusable inside this namespace. The conformance roots use \
127.0.0.1; running them here would fail for a reason unrelated to egress. Bring \
\`lo\` up (\`ip link set lo up\`, needs root or CAP_NET_ADMIN) before running."
fi

if [ "$VERIFY_ONLY" -eq 1 ]; then
  echo "$PROG: verified: egress blocked, loopback usable."
  exit 0
fi

# Set only AFTER the canaries pass, and read by scripts/check_egress_exclusions.py,
# which observes reaches instead of refusing them and must never do that where a
# reach would actually complete.
export HF_EGRESS_ISOLATED=1

# --- run --------------------------------------------------------------------
if [ -n "$DROP_TO" ]; then
  DROP_UID="${DROP_TO%%:*}"
  DROP_GID="${DROP_TO##*:}"
  command -v setpriv >/dev/null 2>&1 ||
    EXIT_CODE=2 fail "--user needs setpriv (util-linux)"
  exec setpriv --reuid="$DROP_UID" --regid="$DROP_GID" --clear-groups -- "$@"
fi

exec "$@"
