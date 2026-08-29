#!/usr/bin/env bash
# Install the pinned Open Policy Agent binary for pilot #11750 into `.opa/opa`.
#
# Usage:  scripts/opa_install.sh [version]      (default: $OPA_VERSION, then $DEFAULT_VERSION)
#
# The binary is NOT committed (45 MB) and NOT fetched at decision time. This is
# a build step: it downloads once, verifies a checksum vendored below, and
# leaves an executable the engine finds without any network access afterwards
# (#11687 — no conformance claim may depend on a service being up).
#
# A version with no vendored checksum is a hard failure, never an unverified
# download: that is the only thing standing between "pinned binary" and
# "whatever the CDN served today".
set -euo pipefail

DEFAULT_VERSION="1.4.2"
VERSION="${1:-${OPA_VERSION:-$DEFAULT_VERSION}}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${REPO_ROOT}/.opa"
DEST="${DEST_DIR}/opa"

# Vendored sha256 sums, keyed "<version>/<asset>". Regenerate for a new version
# from https://openpolicyagent.org/downloads/v<version>/<asset>.sha256 and paste
# them here; do not compute them from the artifact you just downloaded, which
# would verify the download against itself.
read -r -d '' CHECKSUMS <<'EOF' || true
1.4.2/opa_darwin_arm64_static e6cc4a691625958c3ad315eac8a51838ab8a1c13372777736342021fbc6b8cc3
1.4.2/opa_darwin_amd64 5509df39af8bbfb6518f05c7f32966ffc19e6af9f4657ca2fb30405d6256ff7c
1.4.2/opa_linux_amd64_static 2c0ccdbbe0b8e2a5d12d9c42d92f1f34f494ffb32d1f3c4ddc36101be637d66f
1.4.2/opa_linux_arm64_static facd6a9ea375c6299701f86b90b470e52305c5726c4f136e2980fa6123ae9613
EOF

case "$(uname -s)/$(uname -m)" in
	Darwin/arm64) ASSET="opa_darwin_arm64_static" ;;
	Darwin/x86_64) ASSET="opa_darwin_amd64" ;;
	Linux/x86_64) ASSET="opa_linux_amd64_static" ;;
	Linux/aarch64 | Linux/arm64) ASSET="opa_linux_arm64_static" ;;
	*)
		echo "opa-install: unsupported platform $(uname -s)/$(uname -m)" >&2
		exit 1
		;;
esac

EXPECTED="$(printf '%s\n' "$CHECKSUMS" | awk -v k="${VERSION}/${ASSET}" '$1 == k {print $2}')"
if [ -z "$EXPECTED" ]; then
	echo "opa-install: no vendored checksum for ${VERSION}/${ASSET}." >&2
	echo "opa-install: add one to scripts/opa_install.sh before installing." >&2
	exit 1
fi

sha256_of() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | awk '{print $1}'
	else
		shasum -a 256 "$1" | awk '{print $1}'
	fi
}

if [ -x "$DEST" ] && [ "$(sha256_of "$DEST")" = "$EXPECTED" ]; then
	echo "[opa-install] ${DEST} already at ${VERSION} (${ASSET})"
	exit 0
fi

mkdir -p "$DEST_DIR"
TMP="$(mktemp "${DEST_DIR}/opa.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

URL="https://openpolicyagent.org/downloads/v${VERSION}/${ASSET}"
echo "[opa-install] downloading ${URL}"
curl -fsSL --max-time 300 -o "$TMP" "$URL"

ACTUAL="$(sha256_of "$TMP")"
if [ "$ACTUAL" != "$EXPECTED" ]; then
	echo "opa-install: checksum mismatch for ${ASSET}" >&2
	echo "opa-install:   expected ${EXPECTED}" >&2
	echo "opa-install:   actual   ${ACTUAL}" >&2
	exit 1
fi

chmod +x "$TMP"
mv "$TMP" "$DEST"
trap - EXIT
echo "[opa-install] installed $("$DEST" version | head -1) at ${DEST}"
