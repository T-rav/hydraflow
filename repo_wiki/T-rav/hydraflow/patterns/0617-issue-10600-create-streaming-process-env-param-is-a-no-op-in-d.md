---
id: 0617
topic: patterns
source_issue: 10600
source_phase: plan
created_at: 2026-07-26T12:25:53.446760+00:00
status: superseded
corroborations: 1
superseded_by: 0659
---

# create_streaming_process env= param is a no-op in docker

Inject per-spawn environment via `_build_env`, not the `env=` parameter of `DockerRunner.create_streaming_process`. That parameter is marked `# noqa: ARG002` — passing it naively no-ops inside docker containers and only takes effect on host runs. **Why:** Prevents environment variables like `ANTHROPIC_BASE_URL` from being silently dropped on container spawns.
