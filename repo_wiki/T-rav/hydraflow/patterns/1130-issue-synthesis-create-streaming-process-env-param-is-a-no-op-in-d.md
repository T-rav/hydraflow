---
id: 1130
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T08:27:46.944133+00:00
status: active
corroborations: 1
supersedes: 1061
---

# create_streaming_process env= param is a no-op in docker

Inject per-spawn environment via `_build_env`, not the `env=` parameter of `DockerRunner.create_streaming_process`. That parameter is marked `# noqa: ARG002` — passing it naively no-ops inside docker containers and only takes effect on host runs.

Example: Use `_build_env` to set `ANTHROPIC_BASE_URL` on container spawns.

**Why:** Prevents environment variables like `ANTHROPIC_BASE_URL` from being silently dropped on container spawns.
