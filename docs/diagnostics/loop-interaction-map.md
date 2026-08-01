# Loop-Interaction Map (#10823)

Read-only diagnostic — generated 2026-08-01 over the trailing **8 weeks** (756 merges). Surfaces the population-level pathology no per-loop series shows: where one loop's fix is another's disturbance. Loop attribution is not attempted (not derivable — see #10820); this maps the contested *surfaces*. Read alongside the #10820 fingerprint and the concentration god-files.

## Contested surfaces (fix-as-disturbance)

Files where content is repeatedly **added and removed** — a surface two subsystems keep undoing. Ranked by reversal churn = min(total added, total deleted); regen artifacts excluded.

| # | Path | Reversal churn | +added | −deleted | Merges |
|---|---|---|---|---|---|
| 1 | `src/review_phase/_phase.py` | **526** | 1287 | 526 | 13 |
| 2 | `src/plan_phase.py` | **447** | 1209 | 447 | 14 |
| 3 | `src/ui/src/components/EpicOutcomeCards.jsx` | **418** | 418 | 418 | 2 |
| 4 | `src/config.py` | **347** | 3629 | 347 | 128 |
| 5 | `src/ui/src/components/StreamView.jsx` | **343** | 343 | 595 | 16 |
| 6 | `tests/test_shape_phase.py` | **338** | 338 | 741 | 4 |
| 7 | `tests/test_openrouter_provider.py` | **337** | 337 | 337 | 2 |
| 8 | `src/pr_manager.py` | **291** | 1062 | 291 | 36 |
| 9 | `tests/test_review_phase_core.py` | **276** | 1305 | 276 | 7 |
| 10 | `src/dashboard_routes/_routes.py` | **275** | 831 | 275 | 19 |
| 11 | `src/review_advisor.py` | **229** | 340 | 229 | 7 |
| 12 | `src/skill_prompt_eval_loop.py` | **215** | 984 | 215 | 13 |
| 13 | `tests/test_dashboard_routes_repo.py` | **215** | 240 | 215 | 3 |
| 14 | `tests/sandbox_scenarios/scenarios/s51_convergence_oscillation.py` | **212** | 212 | 212 | 4 |
| 15 | `src/ui/src/operator/OperatorConsole.jsx` | **205** | 506 | 205 | 15 |

## Logical coupling (files that change together)

File pairs co-modified across merges (temporal coupling). God-files surface as hubs — consistent with `erosion.concentration`.

| # | File A | File B | Co-changes |
|---|---|---|---|
| 1 | `src/config.py` | `src/models.py` | 34 |
| 2 | `src/config.py` | `src/service_registry.py` | 30 |
| 3 | `src/models.py` | `tests/test_state_tracking.py` | 30 |
| 4 | `src/config.py` | `tests/scenarios/catalog/loop_registrations.py` | 28 |
| 5 | `src/config.py` | `src/orchestrator.py` | 26 |
| 6 | `src/config.py` | `tests/test_state_tracking.py` | 25 |
| 7 | `src/config.py` | `src/dashboard_routes/_control_routes.py` | 22 |
| 8 | `src/orchestrator.py` | `src/service_registry.py` | 22 |
| 9 | `src/service_registry.py` | `tests/scenarios/catalog/loop_registrations.py` | 22 |
| 10 | `src/config.py` | `src/dashboard_routes/_common.py` | 21 |
| 11 | `src/dashboard_routes/_common.py` | `src/ui/src/constants.js` | 21 |
| 12 | `src/models.py` | `src/orchestrator.py` | 21 |
| 13 | `src/orchestrator.py` | `src/ui/src/constants.js` | 21 |
| 14 | `src/service_registry.py` | `src/ui/src/constants.js` | 21 |
| 15 | `src/mockworld/fakes/fake_github.py` | `src/pr_manager.py` | 21 |

## Cross-reference
- **God-file AND contested** (high blast radius + fix-as-disturbance): `src/config.py`
