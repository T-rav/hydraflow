"""What the director's process actually receives (#11537, ADR-0137 S1/S2).

`build_scrubbed_env` is a pure function and is tested as one elsewhere. That
proves the *filter*; it proves nothing about what is fed to it, and the first
version of this runner fed it an empty mapping — which satisfied every scrub
assertion while quietly implementing `env -i`. S1 is explicit that this is "an
allow-list filter over the parent environment, not a literal `env -i`: PATH,
LANG, LC_ALL and TMPDIR are inherited by design", and the first casualty of
getting it wrong is PATH, so the CLI is not even findable.

So these tests drive the runner and inspect the env it hands its spawner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from director_sandbox import DirectorSandboxError
from director_turn_runner import DirectorTurnRunner
from execution import SimpleResult

if TYPE_CHECKING:
    from collections.abc import Sequence


class SpawnRecorder:
    """A `SubprocessRunner` that records what it was asked to run."""

    def __init__(self, stdout: str = "") -> None:
        self.envs: list[dict[str, str]] = []
        self.cwds: list[str | None] = []
        self.argvs: list[list[str]] = []
        self._stdout = stdout

    async def run_simple(self, cmd: Sequence[str], **kwargs: Any) -> SimpleResult:
        self.envs.append(dict(kwargs.get("env") or {}))
        self.cwds.append(kwargs.get("cwd"))
        self.argvs.append(list(cmd))
        return SimpleResult(stdout=self._stdout, stderr="", returncode=0)


async def _mint() -> dict[str, str]:
    return {
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:8080",
        "ANTHROPIC_AUTH_TOKEN": "hf-virtual-key",
    }


def _runner(spawner: SpawnRecorder, **kwargs: Any) -> DirectorTurnRunner:
    return DirectorTurnRunner(
        runner=spawner,  # type: ignore[arg-type]
        source_env={
            "PATH": "/opt/bin:/usr/bin",
            "LANG": "en_GB.UTF-8",
            "ANTHROPIC_API_KEY": "sk-operator-real",
            "GH_TOKEN": "ghp_operator_real",
        },
        mint_credential=_mint,
        **kwargs,
    )


#: One env var per row. Four tests reading ``envs[0][key] == value`` are one
#: parametrize waiting to happen; the reason each row exists is kept with it.
_EXPECTED_ENV = (
    pytest.param(
        "PATH",
        "/opt/bin:/usr/bin",
        # The regression that motivated this file: an empty source mapping left
        # PATH at os.defpath, so `claude` was unfindable on any host with a
        # non-standard install location and the whole feature was inert.
        id="path-is-inherited",
    ),
    pytest.param(
        "LANG",
        "en_GB.UTF-8",
        # S1 names LANG among the variables inherited by design.
        id="locale-is-inherited",
    ),
    pytest.param(
        "ANTHROPIC_AUTH_TOKEN",
        "hf-virtual-key",
        # S2's one permitted credential, minted per turn.
        id="the-minted-token-reaches-the-turn",
    ),
    pytest.param(
        "ANTHROPIC_BASE_URL",
        "http://127.0.0.1:8080",
        # ...pointed at the gateway that minted it, never at the native endpoint.
        id="the-minted-endpoint-reaches-the-turn",
    ),
)


@pytest.mark.parametrize(("key", "expected"), _EXPECTED_ENV)
async def test_the_turn_receives_the_variable(key: str, expected: str) -> None:
    spawner = SpawnRecorder()

    await _runner(spawner).run_turn("hi")

    assert spawner.envs[0][key] == expected


class TestWhatMustNotSurviveTheAllowList:
    async def test_an_operator_provider_key_does_not_survive(self) -> None:
        spawner = SpawnRecorder()

        await _runner(spawner).run_turn("hi")

        assert "ANTHROPIC_API_KEY" not in spawner.envs[0]

    async def test_a_github_token_does_not_survive(self) -> None:
        spawner = SpawnRecorder()

        await _runner(spawner).run_turn("hi")

        assert "GH_TOKEN" not in spawner.envs[0]


class TestTheMintedKeyIsReleased:
    async def test_the_key_is_revoked_after_the_turn(self) -> None:
        # A director turn is short; leaving the key alive until its TTL widens
        # the window a leaked sandbox path could be replayed from.
        revoked: list[dict[str, str]] = []

        async def _revoke(credential: dict[str, str]) -> None:
            revoked.append(credential)

        await _runner(SpawnRecorder(), revoke_credential=_revoke).run_turn("hi")

        assert revoked == [await _mint()]

    async def test_a_failed_revoke_does_not_fail_the_turn(self) -> None:
        async def _revoke(credential: dict[str, str]) -> None:
            raise RuntimeError("gateway unreachable")

        result = await _runner(
            SpawnRecorder(stdout=""), revoke_credential=_revoke
        ).run_turn("hi")

        assert result.timed_out is False


class TestPreflightRefusesWithoutACredential:
    async def test_no_provider_at_all_refuses(self) -> None:
        # Running credential-free would fill the shadow log with authentication
        # failures that look like a flaky model rather than an unconfigured
        # gateway. ADR-0137 S2 permits exactly one credential; without it the
        # director must not run.
        runner = DirectorTurnRunner(
            runner=SpawnRecorder(stdout="2.1.239 (Claude Code)"),  # type: ignore[arg-type]
            source_env={"PATH": "/usr/bin"},
        )

        with pytest.raises(DirectorSandboxError, match="no gateway credential"):
            await runner.preflight()

    async def test_a_provider_that_mints_nothing_refuses(self) -> None:
        async def _empty() -> dict[str, str]:
            return {}

        runner = DirectorTurnRunner(
            runner=SpawnRecorder(stdout="2.1.239 (Claude Code)"),  # type: ignore[arg-type]
            source_env={"PATH": "/usr/bin"},
            mint_credential=_empty,
        )

        with pytest.raises(DirectorSandboxError, match="no ANTHROPIC_AUTH_TOKEN"):
            await runner.preflight()

    async def test_a_mint_failure_refuses_with_its_cause(self) -> None:
        async def _boom() -> dict[str, str]:
            raise RuntimeError("HYDRAFLOW_GATEWAY_CONTROL_TOKEN is unset")

        runner = DirectorTurnRunner(
            runner=SpawnRecorder(stdout="2.1.239 (Claude Code)"),  # type: ignore[arg-type]
            source_env={"PATH": "/usr/bin"},
            mint_credential=_boom,
        )

        with pytest.raises(DirectorSandboxError, match="could not be minted"):
            await runner.preflight()

    async def test_a_wired_provider_lets_preflight_through(self) -> None:
        runner = DirectorTurnRunner(
            runner=SpawnRecorder(stdout="2.1.239 (Claude Code)"),  # type: ignore[arg-type]
            source_env={"PATH": "/usr/bin"},
            mint_credential=_mint,
        )

        assert await runner.preflight() == "2.1.239"


class TestTheProductionPathReadsTheRealEnvironment:
    """The default branch of ``_parent_env()`` — the one production takes.

    Every other test in this file injects ``source_env``, which is exactly why
    it needed writing: reverting ``_parent_env`` to the B1 regression
    (``dict(self._source_env or {})``) left the whole file green, so the fix for
    "the allow-list was filtering nothing" was itself unguarded on the only path
    that ships.
    """

    async def test_path_is_inherited_from_the_real_process_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", "/sentinel/bin")
        spawner = SpawnRecorder()
        runner = DirectorTurnRunner(
            runner=spawner,  # type: ignore[arg-type]
            mint_credential=_mint,
        )

        await runner.run_turn("hi")

        assert spawner.envs[0]["PATH"] == "/sentinel/bin"

    async def test_a_secret_in_the_real_environment_still_does_not_survive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-really-in-os-environ")
        spawner = SpawnRecorder()
        runner = DirectorTurnRunner(
            runner=spawner,  # type: ignore[arg-type]
            mint_credential=_mint,
        )

        await runner.run_turn("hi")

        assert "ANTHROPIC_API_KEY" not in spawner.envs[0]

    async def test_the_environment_is_read_at_spawn_not_at_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A runner built at the composition root outlives many turns; capturing
        # os.environ once would pin whatever the process happened to hold at
        # boot.
        spawner = SpawnRecorder()
        runner = DirectorTurnRunner(
            runner=spawner,  # type: ignore[arg-type]
            mint_credential=_mint,
        )
        monkeypatch.setenv("PATH", "/changed/after/construction")

        await runner.run_turn("hi")

        assert spawner.envs[0]["PATH"] == "/changed/after/construction"


class TestABoundLeaseMakesTheTurnNameItsModel:
    """#11541 / ADR-0141 §D1: the director's own key is now route-bound.

    A route-bound key commits its spawn to exactly one model — the gateway's
    data plane refuses any body naming another — so a bound turn must pass
    ``--model``. An *unbound* turn must not, or every host with the canary
    disarmed would silently start pinning a model it never pinned before.
    """

    async def test_an_unbound_turn_names_no_model(self) -> None:
        spawner = SpawnRecorder()

        await DirectorTurnRunner(
            runner=spawner,  # type: ignore[arg-type]
            mint_credential=_mint,
        ).run_turn("hi")

        assert "--model" not in spawner.argvs[0]

    async def test_a_lease_that_reports_no_binding_names_no_model(self) -> None:
        # ``bound_model_for`` returns "" for a v1 lease, and that must read as
        # "unbound" rather than as an empty ``--model`` argument.
        spawner = SpawnRecorder()

        await DirectorTurnRunner(
            runner=spawner,  # type: ignore[arg-type]
            mint_credential=_mint,
            bound_model=lambda _env: "",
        ).run_turn("hi")

        assert "--model" not in spawner.argvs[0]

    async def test_a_bound_turn_spawns_on_the_binding_s_model(self) -> None:
        spawner = SpawnRecorder()

        await DirectorTurnRunner(
            runner=spawner,  # type: ignore[arg-type]
            mint_credential=_mint,
            bound_model=lambda _env: "claude-sonnet-4-6",
        ).run_turn("hi")

        argv = spawner.argvs[0]
        assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"

    async def test_the_binding_is_read_from_the_turns_own_credential(self) -> None:
        # Not from config and not from a captured value: the mint and the spawn
        # must not be able to disagree about the binding, so only one of them
        # decides it and the other reads it off the lease.
        seen: list[dict[str, str]] = []

        def _bound(env: dict[str, str]) -> str:
            seen.append(dict(env))
            return "claude-opus-4-7"

        await DirectorTurnRunner(
            runner=SpawnRecorder(),  # type: ignore[arg-type]
            mint_credential=_mint,
            bound_model=_bound,
        ).run_turn("hi")

        assert seen[0]["ANTHROPIC_AUTH_TOKEN"] == "hf-virtual-key"
