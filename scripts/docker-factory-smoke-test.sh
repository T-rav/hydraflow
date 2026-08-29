#!/usr/bin/env bash
# Smoke test for the factory image (Dockerfile.factory).
#
# Run INSIDE the image:
#   docker run --rm --entrypoint bash ghcr.io/t-rav/hydraflow-factory:latest \
#     /opt/hydraflow/scripts/docker-factory-smoke-test.sh
#
# Checks the things that actually break: the interpreter the entrypoint uses,
# whether the app imports, whether the dashboard was built in, and that the
# image ships no baked-in target repo.
set -euo pipefail

VENV_PY=/opt/hydraflow-venv/bin/python
fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "ok: $*"; }

# 1. The entrypoint's interpreter must exist AND carry the dependencies.
#    A bare `python` here resolves to the system interpreter, which has none of
#    them — the failure this test exists to catch.
[ -x "$VENV_PY" ] || fail "$VENV_PY missing or not executable"
ok "venv interpreter present"

"$VENV_PY" -c 'import pydantic, fastapi' >/dev/null 2>&1 \
  || fail "venv interpreter cannot import runtime deps (pydantic/fastapi)"
ok "runtime dependencies importable"

# 2. The app itself must import — this is what `-m server` does first.
"$VENV_PY" -c 'import server' >/dev/null 2>&1 \
  || fail "import server failed under the venv interpreter"
ok "server imports"

# 3. --version must answer without booting the event loop.
"$VENV_PY" -m server --version >/dev/null 2>&1 \
  || fail "server --version did not answer"
ok "server --version answers"

# 4. The dashboard must be baked in. The server degrades gracefully without
#    ui/dist, so its absence is SILENT at runtime — a UI-less factory image
#    looks healthy and serves no UI. Assert it here instead.
[ -f /opt/hydraflow/src/ui/dist/index.html ] \
  || fail "src/ui/dist/index.html missing — the dashboard was not built into the image"
ok "dashboard built in"

# 5. No baked target repo. The factory must not ship pointed at someone's
#    repository; the operator names one at run time.
if [ -n "${HYDRAFLOW_GITHUB_REPO:-}" ]; then
  fail "HYDRAFLOW_GITHUB_REPO is baked into the image (${HYDRAFLOW_GITHUB_REPO})"
fi
ok "no target repo baked in"

# 6. Data dir must be writable by the runtime user, or the factory cannot persist.
[ -w "${HYDRAFLOW_DATA_DIR:-/data}" ] \
  || fail "${HYDRAFLOW_DATA_DIR:-/data} is not writable by $(id -un)"
ok "data dir writable"

echo "factory image smoke test PASSED"
