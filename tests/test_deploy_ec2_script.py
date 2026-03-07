"""Regression tests for the EC2 deploy helper script."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "deploy" / "ec2" / "deploy-hydraflow.sh"


def _write_fake_curl(response: str) -> Path:
    """Create a fake curl binary under the repo root so it can execute."""
    fd, path = tempfile.mkstemp(prefix="fake-curl-", suffix=".sh", dir=REPO_ROOT)
    fake = Path(path)
    with os.fdopen(fd, "w") as fh:
        fh.write(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [[ -n "${CURL_CALL_LOG:-}" ]]; then\n'
            '  printf "%s\\n" "$*" >> "${CURL_CALL_LOG}"\n'
            "fi\n"
            "cat <<'JSON'\n"
            f"{response}\n"
            "JSON\n"
        )
    fake.chmod(0o755)
    return fake


def _run_install(env_overrides: dict[str, str]) -> None:
    env = os.environ.copy()
    env.update(env_overrides)
    subprocess.run(
        ["bash", str(SCRIPT_PATH), "install"],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )


def test_install_action_copies_unit_into_custom_directory(tmp_path):
    """The install verb should copy the unit file into SYSTEMD_DIR."""
    systemd_dir = tmp_path / "systemd"
    _run_install({"SYSTEMD_DIR": str(systemd_dir)})

    unit_path = systemd_dir / "hydraflow.service"
    assert unit_path.exists(), "Expected hydraflow.service to be installed"
    contents = unit_path.read_text()
    assert "deploy/ec2/deploy-hydraflow.sh run" in contents


def test_install_action_invokes_systemctl_when_allowed(tmp_path):
    """When permitted, install should call systemctl enable/daemon-reload."""
    systemd_dir = tmp_path / "units"
    log_file = tmp_path / "systemctl.log"
    with tempfile.NamedTemporaryFile(
        "w",
        dir=REPO_ROOT,
        delete=False,
        prefix="fake-systemctl-",
    ) as fake_fd:
        fake_fd.write(
            '#!/usr/bin/env bash\nset -euo pipefail\necho "$*" >> "${SYSTEMCTL_LOG}"\n'
        )
        fake_path = Path(fake_fd.name)
    fake_path.chmod(0o755)

    try:
        _run_install(
            {
                "SYSTEMD_DIR": str(systemd_dir),
                "SERVICE_NAME": "hf-prod",
                "SYSTEMCTL_BIN": str(fake_path),
                "SYSTEMCTL_ALLOW_USER": "1",
                "SYSTEMCTL_LOG": str(log_file),
            }
        )
    finally:
        fake_path.unlink(missing_ok=True)

    unit_path = systemd_dir / "hf-prod.service"
    assert unit_path.exists()
    commands = log_file.read_text().strip().splitlines()
    # The helper should reload units then enable/start the service.
    assert commands == [
        "daemon-reload",
        "enable --now hf-prod.service",
    ]


def test_health_command_uses_curl_and_prints_payload(tmp_path: Path) -> None:
    """`health` should hit the configured URL and surface the JSON payload."""
    fake_curl = _write_fake_curl('{"ready": true, "status": "ok"}')
    log_file = tmp_path / "curl.log"
    env = os.environ.copy()
    env.update(
        {
            "CURL_BIN": str(fake_curl),
            "CURL_CALL_LOG": str(log_file),
            "HEALTHCHECK_URL": "http://internal/healthz",
        }
    )

    try:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "health"],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
    finally:
        fake_curl.unlink(missing_ok=True)

    assert '"ready": true' in result.stdout
    assert "ready=true" in result.stdout
    assert log_file.read_text().strip() == "-fsS http://internal/healthz"


def test_health_command_can_fail_when_not_ready(tmp_path: Path) -> None:
    """When readiness is enforced, non-ready payloads should exit non-zero."""
    fake_curl = _write_fake_curl('{"ready": false, "status": "degraded"}')
    env = os.environ.copy()
    env.update(
        {
            "CURL_BIN": str(fake_curl),
            "HEALTHCHECK_URL": "http://internal/healthz",
            "HEALTHCHECK_REQUIRE_READY": "1",
        }
    )

    try:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "health"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        fake_curl.unlink(missing_ok=True)

    assert result.returncode != 0
    assert "Service is not ready" in result.stdout
