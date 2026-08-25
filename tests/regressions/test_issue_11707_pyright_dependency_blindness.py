"""Canary: pyright must actually see the project's dependencies (#11707).

pyright's answer used to depend on how it was invoked. Run through ``uv run``
(what ``make quality`` and CI do, with ``VIRTUAL_ENV`` set) it resolved the
project's site-packages. Run as the bare ``.venv/bin/pyright`` it resolved a
different interpreter, could not see site-packages, and **every ``py.typed``
dependency degraded to ``Unknown``** — ``BaseModel``, ``FastAPI``,
``httpx.AsyncClient`` — so attribute checking silently stopped on everything
derived from them. ``reportMissingImports = false`` and
``reportMissingTypeStubs = false`` suppressed the two diagnostics that would
have announced it, leaving a type check that was quietly green.

``venvPath``/``venv`` in ``[tool.pyright]`` fix that by making the config
self-sufficient. A config fix alone rots — a new pyright, a restructured venv,
a changed runner, and the whole type check goes blind again with nothing red.
So this module runs the **bare** binary, with ``VIRTUAL_ENV`` scrubbed, over a
fixture holding a deliberate pydantic attribute typo, and asserts pyright still
reports it. It is a standing canary rather than a historical pin: it fails on
environment and toolchain drift, not only on someone editing the config back.

Cost: one pyright process over a single file, ~2s wall on a warm host — but
CI's Regression Tests lane runs ``tests/regressions/`` with ``--forked``, and
pytest-forked rebuilds the module-scoped fixture inside each fork, so it is
one process per test there (~3 today). Adding a test to
``TestPyrightSeesItsDependencies`` costs another. The pyright wheel bundles
its own JS, so there is no network fetch and no npm download; it needs only
the ``node`` that ``make typecheck`` already needs.

Portable across checkouts that keep their venv elsewhere — the agent image
puts it at ``/opt/hydraflow-venv``, a fresh worktree has none until
``make env``. That is handled by retargeting the derived config onto the
interpreter actually running the tests (see ``_derive_canary_config``), NOT by
pyright's PATH fallback, which ``_hermetic_bin_dir`` deliberately starves. The
canary reddens only where pyright genuinely cannot see the dependency.

Mutation-proven **under ``uv run --active``**, which is how CI and
``make quality`` launch this suite — not merely under a bare ``python -m
pytest``. That distinction was not academic: an earlier version scrubbed
``VIRTUAL_ENV`` but left ``PATH`` alone, so pyright's PATH fallback found the
project venv anyway and the canary stayed green with ``venvPath``/``venv``
deleted. It could not see its own subject in the only contexts where it runs.
See ``_bare_path``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    Path(__file__).resolve().parent / "_pyright_canary" / "pydantic_attribute_typo.py"
)
TYPO_ATTRIBUTE = "definitely_not_a_field"
PYRIGHT_TIMEOUT_SECONDS = 300

# Config keys whose values are paths resolved relative to the config file. The
# canary's derived config lives in a tmp dir, so these are rebased onto
# REPO_ROOT — otherwise `venvPath = "."` would point at the tmp dir and the
# canary would measure its own scaffolding instead of the project's config.
_PATH_KEYS = ("venvPath", "typeshedPath", "stubPath", "pythonPath")
_PATH_LIST_KEYS = ("extraPaths",)
# Keys the derivation overwrites outright rather than rebasing.
_OVERWRITTEN_KEYS = ("include", "exclude", "ignore")
# An allowlist rots silently: a path-valued key added to [tool.pyright] that
# nobody rebases would resolve against the tmp dir, and nothing would redden.
# Anything that LOOKS path-valued and is unhandled fails loudly instead.
_PATH_LIKE_KEY_RE = re.compile(
    r"(?i)(paths?|roots?|dirs?|executionEnvironments)$",
)

# The one venv declaration this canary knows how to retarget (see
# `_derive_canary_config`). Pinned by
# `TestPyrightConfigIsSelfSufficient::test_venv_is_declared_relative_to_the_config`.
_CANONICAL_VENV = (".", ".venv")

# Environment that makes an invocation "bare": no active virtualenv for pyright
# to inherit, which is exactly how an agent running `.venv/bin/pyright` by hand
# invokes it. If the project config is self-sufficient the answer is unchanged.
_VENV_ENV_KEYS = (
    "VIRTUAL_ENV",
    "VIRTUAL_ENV_PROMPT",
    "PYTHONHOME",
    "PYTHONPATH",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
)


def _project_pyright_config() -> dict[str, Any]:
    """Return ``[tool.pyright]`` from the project's pyproject.toml."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return dict(data["tool"]["pyright"])


def _bare_pyright_executable() -> Path:
    """The pyright binary of the venv running these tests, invoked directly.

    Deliberately not skippable. pyright is a declared dev dependency that
    ``uv sync --all-extras`` installs, so every environment sanctioned to run
    this suite has it. Skipping when it is missing would turn "the type checker
    is gone" into silence — the same shape of blindness this module exists to
    catch.
    """
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    name = "pyright.exe" if os.name == "nt" else "pyright"
    candidate = Path(sys.prefix) / bin_dir / name
    if candidate.exists():
        return candidate
    found = shutil.which(name)
    if found is not None:
        return Path(found)
    raise AssertionError(
        f"pyright is not installed: no {candidate} and none on PATH. This is not a "
        "second gate on pyright's presence — `make typecheck` and CI's Type Check "
        "job own that and fail outright without it. It means a lane running this "
        "canary lost its dev extras: either restore them (`uv sync --all-extras`) "
        "or deselect this file there, the way ci.yml's time-travel lane does. "
        "Deliberately NOT a skip: a canary that can go quiet is the exact silence "
        "it exists to catch."
    )


def _declared_venv_dir(config: dict[str, Any]) -> Path | None:
    """The venv directory ``[tool.pyright]`` points at, or None if it declares none."""
    venv_path = config.get("venvPath")
    venv = config.get("venv")
    if venv_path is None or venv is None:
        return None
    return (REPO_ROOT / str(venv_path) / str(venv)).resolve()


def _hermetic_bin_dir(config_dir: Path) -> Path:
    """A PATH holding exactly one executable: ``node``.

    Scrubbing ``VIRTUAL_ENV`` does not make an invocation bare, and neither
    does dropping virtualenv entries from PATH. When pyright's config declares
    no venv it searches PATH for an interpreter, and **any** python it finds
    with pydantic installed answers the question for it. Two rounds of review
    found this the hard way: first ``uv run``'s own venv ``bin`` kept the
    canary green with the fix reverted, then — after that was filtered out —
    this host's ``/usr/bin/python3``, which has pydantic 2.11.7, did the same.
    Filtering PATH tests the wrong predicate ("is this a virtualenv?") for the
    property that matters ("can this interpreter import pydantic?"), and one
    ``pip install --user pydantic`` re-opens the hole with nothing red.

    So the search is starved instead of filtered: no python on PATH at all,
    which leaves ``venvPath``/``venv`` as the only way pyright can resolve the
    dependency. pyright itself needs exactly one executable — ``node`` — so
    PATH holds a directory containing exactly that, symlinked in. Resolving it
    here also means pyright never falls through to ``nodeenv``, which would
    download a node over the network.
    """
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "`node` is not on PATH, so pyright cannot run at all — it is a "
            "JavaScript program with a Python launcher. Install Node 20.19+/22.12+ "
            "(nvm counts). Not skipping: a silent pass here would mean nothing "
            "checked types, which is the failure this module exists to catch."
        )
    bin_dir = config_dir / "_bin"
    bin_dir.mkdir(exist_ok=True)
    link = bin_dir / "node"
    if not link.exists():
        link.symlink_to(node)
    return bin_dir


def _derive_canary_config(config_dir: Path) -> None:
    """Materialise the project's pyright config with the fixture as its only input.

    Every setting is inherited from ``pyproject.toml`` — including the
    ``reportMissingImports``/``reportMissingTypeStubs`` suppressions that made
    the original failure silent — so removing ``venvPath``/``venv`` there
    reddens this canary. Only the file selection and the relative path bases
    are overridden.
    """
    config = _project_pyright_config()
    handled = {*_PATH_KEYS, *_PATH_LIST_KEYS, *_OVERWRITTEN_KEYS}
    unhandled = sorted(
        key for key in config if key not in handled and _PATH_LIKE_KEY_RE.search(key)
    )
    assert not unhandled, (
        f"[tool.pyright] gained path-valued key(s) this canary does not rebase: "
        f"{unhandled}. Their values would resolve against the canary's tmp config "
        "directory instead of the repo, so the canary would quietly measure its own "
        "scaffolding. Add them to _PATH_KEYS or _PATH_LIST_KEYS."
    )
    for key in _PATH_KEYS:
        if key in config:
            config[key] = str((REPO_ROOT / str(config[key])).resolve())
    for key in _PATH_LIST_KEYS:
        if key in config:
            config[key] = [
                str((REPO_ROOT / str(path)).resolve()) for path in config[key]
            ]

    # pyright only analyses files UNDER the config root, so the fixture is
    # copied in rather than referenced where it lives. Referencing it in place
    # yields "0 files analyzed" and a green exit — which is why
    # `test_the_fixture_was_actually_analysed` exists.
    (config_dir / FIXTURE.name).write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    config["include"] = [FIXTURE.name]
    # `exclude` must stay non-empty: pyright falls back to its defaults
    # (which include `**/.*`) when the list is empty, and a dot component in
    # TMPDIR would then silently exclude the fixture. `ignore` is cleared so a
    # future project-wide suppression cannot mute the canary.
    config["exclude"] = ["**/node_modules", "**/__pycache__"]
    config["ignore"] = []

    # A checkout whose venv is not at the declared path — the agent image keeps
    # it at /opt/hydraflow-venv, a fresh worktree has none until `make env` —
    # still has ONE: the interpreter running this test. Retarget onto it so the
    # canary asserts "the config points pyright at a real environment" rather
    # than "the environment sits at this exact path".
    #
    # Gated on the CANONICAL declaration, not merely on "something was
    # declared". Retargeting anything absent would swallow the regressions it
    # exists to catch: `venv = ".vnev"` and `venvPath = "/nonexistent"` are
    # both genuinely blind on every real invocation, and both went green while
    # this branch fired on any missing directory. A config that declares no
    # venv, a partial pair, or a wrong path is never retargeted.
    project_config = _project_pyright_config()
    declared = (project_config.get("venvPath"), project_config.get("venv"))
    declared_dir = _declared_venv_dir(project_config)
    if (
        declared == _CANONICAL_VENV
        and declared_dir is not None
        and not declared_dir.is_dir()
    ):
        in_use = Path(sys.prefix).resolve()
        config["venvPath"] = str(in_use.parent)
        config["venv"] = in_use.name

    (config_dir / "pyrightconfig.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )


def _run_bare_pyright(config_dir: Path) -> dict[str, Any]:
    """Run the bare pyright binary against the derived config; return its JSON."""
    executable = _bare_pyright_executable()

    env = {k: v for k, v in os.environ.items() if k not in _VENV_ENV_KEYS}
    env["PATH"] = str(_hermetic_bin_dir(config_dir))
    # `--outputjson` already suppresses pyright-python's update check (and the
    # network call behind it); this keeps stderr clean if that ever changes.
    env["PYRIGHT_PYTHON_IGNORE_WARNINGS"] = "1"

    # Fixed argv, repo-local executable, no shell.
    completed = subprocess.run(
        [str(executable), "--project", str(config_dir), "--outputjson"],
        check=False,  # pyright exits non-zero on the deliberate error; that IS the pass
        capture_output=True,
        text=True,
        timeout=PYRIGHT_TIMEOUT_SECONDS,
        env=env,
        cwd=str(config_dir),
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - environment failure
        raise AssertionError(
            "pyright produced no parseable JSON — the type checker itself is broken.\n"
            f"exit={completed.returncode}\nstdout={completed.stdout!r}\nstderr={completed.stderr!r}"
        ) from exc


@pytest.fixture(scope="module")
def bare_pyright_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One bare pyright run over the canary fixture, shared by this module."""
    config_dir = tmp_path_factory.mktemp("pyright_canary")
    _derive_canary_config(config_dir)
    return _run_bare_pyright(config_dir)


def _diagnostics(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(result.get("generalDiagnostics", []))


def _venv_state_hint() -> str:
    """Name the actual cause, because the two look identical from the outside.

    A deleted config key and an unsynced checkout both end as "pyright cannot
    see pydantic". They need opposite fixes, and an earlier version of this
    hint told the reader to run `make env` in the first case — which cannot
    fix a deleted key, and whose closing "before reading anything else into
    this failure" sent them away from the real cause.
    """
    config = _project_pyright_config()
    declared = (config.get("venvPath"), config.get("venv"))
    if declared[0] is None or declared[1] is None:
        return (
            "\nNOTE: [tool.pyright] declares "
            f"venvPath={declared[0]!r} venv={declared[1]!r} — an incomplete pair, so "
            "pyright has no environment to resolve against. THIS IS THE REGRESSION, "
            'not a local environment problem: restore `venvPath = "."` and '
            '`venv = ".venv"`. Running `make env` will not help.'
        )
    venv_dir = _declared_venv_dir(config)
    if venv_dir is None or venv_dir.is_dir():
        return ""
    if declared != _CANONICAL_VENV:
        return (
            f"\nNOTE: [tool.pyright] points at {venv_dir}, which does not exist. That "
            "is a wrong declaration, not a local environment problem — pyright is "
            "blind on every invocation with it. Fix the config."
        )
    return (
        f"\nNOTE: the declared venv {venv_dir} does not exist, so the canary retargeted "
        f"onto the interpreter running these tests ({sys.prefix}) — and that one cannot "
        "import pydantic either. A fresh git worktree has no .venv until something "
        "syncs one: try `make env` in this checkout."
    )


class TestPyrightSeesItsDependencies:
    """The bare binary must resolve py.typed dependencies from the config alone."""

    def test_the_fixture_was_actually_analysed(
        self, bare_pyright_result: dict[str, Any]
    ) -> None:
        """Anti-vacuity: a canary that analysed nothing would pass silently."""
        analysed = bare_pyright_result["summary"]["filesAnalyzed"]

        assert analysed == 1, (
            f"pyright analysed {analysed} files, expected exactly 1 ({FIXTURE.name}). "
            "A canary that checks nothing is the same blindness it exists to catch — "
            "most likely the derived config re-acquired an `exclude` entry covering "
            "the fixture, which makes pyright skip explicitly-named files."
        )

    def test_pydantic_basemodel_resolves_to_a_real_type(
        self, bare_pyright_result: dict[str, Any]
    ) -> None:
        """`BaseModel` must not degrade to `Unknown` — that is the root cause."""
        revealed = [
            d["message"]
            for d in _diagnostics(bare_pyright_result)
            if "BaseModel" in d["message"]
        ]

        assert revealed and all("Unknown" not in m for m in revealed), (
            "pyright resolved `pydantic.BaseModel` as Unknown (or not at all) when "
            "invoked as a bare binary. It cannot see the project's site-packages, so "
            "EVERY py.typed dependency degrades to Unknown and attribute checking "
            "silently stops. Check that [tool.pyright] in pyproject.toml still sets "
            f"`venvPath`/`venv` and that they point at a real venv (#11707).{_venv_state_hint()}"
            f"\nrevealed: {revealed}"
        )

    def test_bare_pyright_reports_the_pydantic_attribute_typo(
        self, bare_pyright_result: dict[str, Any]
    ) -> None:
        """The canary proper: a known-bad attribute access must still be an error."""
        attribute_errors = [
            d
            for d in _diagnostics(bare_pyright_result)
            if d.get("rule") == "reportAttributeAccessIssue"
            and TYPO_ATTRIBUTE in d["message"]
        ]

        assert attribute_errors, (
            f"pyright did not report `{TYPO_ATTRIBUTE}` on a pydantic model. The type "
            "check has gone blind: it still exits green, so nothing else will tell you. "
            "This is the #11707 failure mode — pyright resolving a different interpreter "
            "and losing site-packages. Fix the environment or restore `venvPath`/`venv` "
            f"in [tool.pyright]; do not delete this test.{_venv_state_hint()}\n"
            f"diagnostics: {_diagnostics(bare_pyright_result)}"
        )


class TestPyrightConfigIsSelfSufficient:
    """The declaration itself, checked without paying for a pyright run."""

    def test_venv_is_declared_relative_to_the_config(self) -> None:
        """`venvPath` must be repo-relative so a worktree resolves its OWN venv."""
        config = _project_pyright_config()

        assert config.get("venvPath") == "." and config.get("venv") == ".venv", (
            '[tool.pyright] must set `venvPath = "."` and `venv = ".venv"`. Without '
            "them pyright's answer depends on how it is invoked, and the bare-binary "
            "invocation goes silently green (#11707). Repo-relative is deliberate: it "
            "makes a git worktree resolve its own .venv, matching what "
            "`make quality` uses.\n"
            f"actual: venvPath={config.get('venvPath')!r} venv={config.get('venv')!r}"
        )
