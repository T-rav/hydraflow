import { describe, it, expect } from 'vitest'
import { ACTIVE_STATUSES, PIPELINE_STAGES, PIPELINE_LOOPS, INTERVAL_PRESETS, EDITABLE_INTERVAL_WORKERS, REPORT_ISSUE_PRESETS, WORKER_PRESETS, PIPELINE_POLLER_PRESETS, ADR_REVIEWER_PRESETS, DEPENDABOT_MERGE_PRESETS, BACKGROUND_WORKERS, WORKER_GROUPS, WATCHDOG_TIMEOUT_PRESETS } from '../../constants'
import { theme } from '../../theme'
import { toLoops } from '../../operator/model/loops'

describe('ACTIVE_STATUSES', () => {
  it('is an array', () => {
    expect(Array.isArray(ACTIVE_STATUSES)).toBe(true)
  })

  it('contains expected active statuses', () => {
    expect(ACTIVE_STATUSES).toEqual([
      'running', 'testing', 'committing', 'reviewing', 'planning', 'quality_fix',
      'start', 'merge_main', 'merge_fix', 'ci_wait', 'ci_fix', 'merging',
      'evaluating', 'validating', 'retrying', 'fixing',
    ])
  })

  it('includes quality_fix status', () => {
    expect(ACTIVE_STATUSES).toContain('quality_fix')
  })

  it('includes merge_fix status', () => {
    expect(ACTIVE_STATUSES).toContain('merge_fix')
  })

  it('does not include terminal statuses', () => {
    const terminalStatuses = ['queued', 'done', 'failed']
    for (const status of terminalStatuses) {
      expect(ACTIVE_STATUSES).not.toContain(status)
    }
  })
})

describe('PIPELINE_STAGES', () => {
  it('is an array with 6 stages', () => {
    expect(Array.isArray(PIPELINE_STAGES)).toBe(true)
    expect(PIPELINE_STAGES).toHaveLength(6)
  })

  it('contains all pipeline stage keys in order', () => {
    const keys = PIPELINE_STAGES.map(s => s.key)
    expect(keys).toEqual(['triage', 'plan', 'implement', 'review', 'hitl', 'merged'])
  })

  it('has title-case labels for each stage', () => {
    const labels = PIPELINE_STAGES.map(s => s.label)
    expect(labels).toEqual(['Triage', 'Plan', 'Implement', 'Review', 'Needs Human', 'Merged'])
  })

  it('maps each stage to the correct theme color', () => {
    const colorMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, s.color]))
    expect(colorMap).toEqual({
      triage: theme.yellow,
      plan: theme.purple,
      implement: theme.accent,
      review: theme.orange,
      hitl: theme.red,
      merged: theme.green,
    })
  })

  it('assigns roles to active stages and null to merged', () => {
    const roleMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, s.role]))
    expect(roleMap).toEqual({
      triage: 'triage',
      plan: 'planner',
      implement: 'implementer',
      review: 'reviewer',
      hitl: null,
      merged: null,
    })
  })

  it('assigns configKeys to active stages and null to merged', () => {
    const configMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, s.configKey]))
    expect(configMap).toEqual({
      triage: 'max_triagers',
      plan: 'max_planners',
      implement: 'max_workers',
      review: 'max_reviewers',
      hitl: null,
      merged: null,
    })
  })

  it('maps each stage to the correct subtle color', () => {
    const subtleMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, s.subtleColor]))
    expect(subtleMap).toEqual({
      triage: theme.yellowSubtle,
      plan: theme.purpleSubtle,
      implement: theme.accentSubtle,
      review: theme.orangeSubtle,
      hitl: theme.redSubtle,
      merged: theme.greenSubtle,
    })
  })

  it('every stage has key, label, color, subtleColor, role, and configKey properties', () => {
    for (const stage of PIPELINE_STAGES) {
      expect(stage).toHaveProperty('key')
      expect(stage).toHaveProperty('label')
      expect(stage).toHaveProperty('color')
      expect(stage).toHaveProperty('subtleColor')
      expect(stage).toHaveProperty('role')
      expect(stage).toHaveProperty('configKey')
    }
  })

  it('has unique keys', () => {
    const keys = PIPELINE_STAGES.map(s => s.key)
    expect(new Set(keys).size).toBe(keys.length)
  })
})

describe('PIPELINE_LOOPS', () => {
  it('has entries for all worker-bearing pipeline stages (excludes terminal/no-role stages)', () => {
    // PIPELINE_LOOPS are the stages that run workers — i.e. stages with a role.
    // Terminal/no-role stages (merged, hitl) have no loop.
    const stageKeys = PIPELINE_STAGES.filter(s => s.role !== null).map(s => s.key)
    expect(PIPELINE_LOOPS.map(l => l.key)).toEqual(stageKeys)
  })

  it('every loop has key, label, color, dimColor, and configKey properties', () => {
    for (const loop of PIPELINE_LOOPS) {
      expect(loop).toHaveProperty('key')
      expect(loop).toHaveProperty('label')
      expect(loop).toHaveProperty('color')
      expect(loop).toHaveProperty('dimColor')
      expect(loop).toHaveProperty('configKey')
    }
  })

  it('maps each loop to the correct configKey', () => {
    const configMap = Object.fromEntries(PIPELINE_LOOPS.map(l => [l.key, l.configKey]))
    expect(configMap).toEqual({
      triage: 'max_triagers',
      plan: 'max_planners',
      implement: 'max_workers',
      review: 'max_reviewers',
    })
  })
})

describe('INTERVAL_PRESETS', () => {
  it('has expected number of presets', () => {
    expect(INTERVAL_PRESETS).toHaveLength(4)
  })

  it('each preset has label and seconds', () => {
    for (const preset of INTERVAL_PRESETS) {
      expect(preset).toHaveProperty('label')
      expect(preset).toHaveProperty('seconds')
      expect(typeof preset.seconds).toBe('number')
    }
  })

  it('presets are in ascending order', () => {
    for (let i = 1; i < INTERVAL_PRESETS.length; i++) {
      expect(INTERVAL_PRESETS[i].seconds).toBeGreaterThan(INTERVAL_PRESETS[i - 1].seconds)
    }
  })
})

describe('EDITABLE_INTERVAL_WORKERS', () => {
  it('includes report_issue', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('report_issue')).toBe(true)
  })

  it('does not include non-editable workers', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('triage')).toBe(false)
    expect(EDITABLE_INTERVAL_WORKERS.has('health_monitor')).toBe(false)
  })
})

describe('WATCHDOG_TIMEOUT_PRESETS', () => {
  it('has 5 presets', () => {
    expect(WATCHDOG_TIMEOUT_PRESETS).toHaveLength(5)
  })

  it('each preset has label and seconds', () => {
    for (const preset of WATCHDOG_TIMEOUT_PRESETS) {
      expect(preset).toHaveProperty('label')
      expect(preset).toHaveProperty('seconds')
      expect(typeof preset.seconds).toBe('number')
    }
  })

  it('presets are in ascending order', () => {
    for (let i = 1; i < WATCHDOG_TIMEOUT_PRESETS.length; i++) {
      expect(WATCHDOG_TIMEOUT_PRESETS[i].seconds).toBeGreaterThan(WATCHDOG_TIMEOUT_PRESETS[i - 1].seconds)
    }
  })

  it('includes the config defaults (2h normal, 4h LLM)', () => {
    const seconds = WATCHDOG_TIMEOUT_PRESETS.map(p => p.seconds)
    expect(seconds).toContain(7200)
    expect(seconds).toContain(14400)
  })
})

describe('REPORT_ISSUE_PRESETS', () => {
  it('has 4 presets', () => {
    expect(REPORT_ISSUE_PRESETS).toHaveLength(4)
  })

  it('each preset has label and seconds', () => {
    for (const preset of REPORT_ISSUE_PRESETS) {
      expect(preset).toHaveProperty('label')
      expect(preset).toHaveProperty('seconds')
      expect(typeof preset.seconds).toBe('number')
    }
  })

  it('presets are in ascending order', () => {
    for (let i = 1; i < REPORT_ISSUE_PRESETS.length; i++) {
      expect(REPORT_ISSUE_PRESETS[i].seconds).toBeGreaterThan(REPORT_ISSUE_PRESETS[i - 1].seconds)
    }
  })

  it('contains the expected values', () => {
    expect(REPORT_ISSUE_PRESETS).toEqual([
      { label: '30s', seconds: 30 },
      { label: '1m', seconds: 60 },
      { label: '5m', seconds: 300 },
      { label: '10m', seconds: 600 },
    ])
  })
})

describe('DEPENDABOT_MERGE_PRESETS', () => {
  it('has 5 presets from 1h to 24h', () => {
    expect(DEPENDABOT_MERGE_PRESETS).toHaveLength(5)
    expect(DEPENDABOT_MERGE_PRESETS[0].seconds).toBe(3600)
    expect(DEPENDABOT_MERGE_PRESETS[4].seconds).toBe(86400)
  })
})

describe('BACKGROUND_WORKERS dependabot_merge entry', () => {
  it('includes dependabot_merge worker', () => {
    const depMerge = BACKGROUND_WORKERS.find(w => w.key === 'dependabot_merge')
    expect(depMerge).toBeDefined()
    expect(depMerge.label).toBe('Dependabot Merge')
  })
})

describe('EDITABLE_INTERVAL_WORKERS includes dependabot_merge', () => {
  it('dependabot_merge is editable', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('dependabot_merge')).toBe(true)
  })
})

describe('WORKER_PRESETS', () => {
  it('has exactly the expected worker keys', () => {
    expect(Object.keys(WORKER_PRESETS).sort()).toEqual(['adr_reviewer', 'ci_monitor', 'dependabot_merge', 'pipeline_poller', 'report_issue', 'security_patch', 'sentry_ingest', 'stale_issue'])
  })

  it('maps pipeline_poller to PIPELINE_POLLER_PRESETS', () => {
    expect(WORKER_PRESETS.pipeline_poller).toBe(PIPELINE_POLLER_PRESETS)
  })

  it('maps adr_reviewer to ADR_REVIEWER_PRESETS', () => {
    expect(WORKER_PRESETS.adr_reviewer).toBe(ADR_REVIEWER_PRESETS)
  })

  it('maps report_issue to REPORT_ISSUE_PRESETS', () => {
    expect(WORKER_PRESETS.report_issue).toBe(REPORT_ISSUE_PRESETS)
  })
})

describe('WORKER_GROUPS', () => {
  it('has 8 groups', () => {
    expect(WORKER_GROUPS).toHaveLength(8)
  })

  it('every group has key, label, color, and tags', () => {
    for (const g of WORKER_GROUPS) {
      expect(g).toHaveProperty('key')
      expect(g).toHaveProperty('label')
      expect(g).toHaveProperty('color')
      expect(g).toHaveProperty('tags')
      expect(g.tags.length).toBeGreaterThan(0)
    }
  })

  it('every BACKGROUND_WORKERS entry has a valid group', () => {
    const groupKeys = new Set(WORKER_GROUPS.map(g => g.key))
    for (const w of BACKGROUND_WORKERS) {
      expect(groupKeys).toContain(w.group)
    }
  })

  it('every BACKGROUND_WORKERS entry has at least one tag', () => {
    for (const w of BACKGROUND_WORKERS) {
      expect(w.tags.length).toBeGreaterThan(0)
    }
  })
})

// Ratchet guard (#10556): BACKGROUND_WORKERS must cover the FULL background-loop
// registry so the operator Loops panel (src/operator/model/loops.js `toLoops`)
// never buckets a real, reporting loop into the catch-all "Other" group.
//
// `LOOP_REGISTRY_WORKER_NAMES` is the authoritative set of `worker_name`s that
// every `BaseBackgroundLoop` subclass registers (the snake_case name each loop
// passes to `super().__init__(worker_name=...)`, which is also the WS
// `data.worker` key the UI matches on). There is no JS-importable loop registry,
// so it is hardcoded from the backend enumeration:
//   grep -hoE "worker_name\s*=\s*['\"][a-z0-9_]+['\"]" src/*_loop.py
//   (+ the 5 loops whose worker_name is the module-level _WORKER_NAME constant:
//    edge_proposer, entry_evidence, term_proposer, term_pruner, adr_drift_resolver)
// and cross-checked against docs/arch/generated/loops.md + functional_areas.yml.
//
// KEEP IN SYNC: when a loop is added/removed/renamed, update BOTH this list and
// BACKGROUND_WORKERS in constants.js. The count sentinel below will red on drift.
const LOOP_REGISTRY_WORKER_NAMES = [
  'adr_conformance',
  'adr_drift_resolver',
  'adr_reviewer',
  'adr_touchpoint_auditor',
  'auto_agent_preflight',
  'auto_tighten',
  'branch_protection_auditor',
  'ci_monitor',
  'contract_refresh',
  'convergence_oscillation',
  'corpus_learning',
  'cost_budget_watcher',
  'dependabot_merge',
  'detector_calibration',
  'diagnostic',
  'diagram_loop',
  'disturbance_dampener',
  'edge_proposer',
  'entry_evidence',
  'epic_monitor',
  'epic_sweeper',
  'erosion_metrics',
  'escape_ledger',
  'fail_open_monitor',
  'fake_coverage_auditor',
  'fitness_scorecard',
  'flake_tracker',
  'gate_activator',
  'gate_health',
  'github_cache',
  'health_monitor',
  'human_steering',
  'intervention_tally',
  'issue_refinement',
  'label_drift_watcher',
  'live_corpus_replay',
  'log_ingest',
  'memory_backlog',
  'merge_state_watcher',
  'pr_red_repair',
  'pr_unsticker',
  'pricing_refresh',
  'principles_audit',
  'rc_budget',
  'repo_wiki',
  'report_issue',
  'retrospective',
  'runs_gc',
  'sampled_audit',
  'sandbox_failure_fixer',
  'second_order_vitals',
  'security_patch',
  'sentry_ingest',
  'skill_prompt_eval',
  'staging_bisect',
  'staging_promotion',
  'stale_issue',
  'stale_issue_gc',
  'term_proposer',
  'term_pruner',
  'triage_retry',
  'trust_fleet_sanity',
  'wiki_rot_detector',
  'workspace_gc',
]

describe('BACKGROUND_WORKERS loop-registry coverage (#10556)', () => {
  const workerKeys = new Set(BACKGROUND_WORKERS.map(w => w.key))
  const groupKeys = new Set(WORKER_GROUPS.map(g => g.key))

  it('reference registry lists 64 loops (sentinel — update when loops change)', () => {
    // If the backend loop count changes, this red reminds you to reconcile the
    // reference list AND BACKGROUND_WORKERS. See docs/arch/generated/loops.md.
    expect(LOOP_REGISTRY_WORKER_NAMES).toHaveLength(64)
    // No accidental duplicates in the reference list.
    expect(new Set(LOOP_REGISTRY_WORKER_NAMES).size).toBe(64)
  })

  it('every registered loop has a BACKGROUND_WORKERS entry (nothing falls into Other)', () => {
    const missing = LOOP_REGISTRY_WORKER_NAMES.filter(name => !workerKeys.has(name))
    expect(missing).toEqual([])
  })

  it('every registered loop maps to a real functional-area group (never the "other" catch-all)', () => {
    const meta = new Map(BACKGROUND_WORKERS.map(w => [w.key, w.group]))
    for (const name of LOOP_REGISTRY_WORKER_NAMES) {
      const group = meta.get(name)
      // A missing entry defaults to 'other' in toLoops; assert a valid, named group.
      expect(group, `loop "${name}" has no BACKGROUND_WORKERS group`).toBeDefined()
      expect(groupKeys, `loop "${name}" group "${group}" is not a WORKER_GROUPS key`).toContain(group)
    }
  })

  it('the full registry produces no "Other" category in the Loops panel view model', () => {
    // Feed one ok snapshot per registered loop through the real toLoops adapter;
    // the panel's catch-all "Other" bucket must be empty.
    const workers = LOOP_REGISTRY_WORKER_NAMES.map(name => ({
      name,
      status: 'ok',
      last_run: '2026-07-27T00:00:00Z',
      details: {},
      enabled: true,
      interval_seconds: 300,
    }))
    const vm = toLoops(workers)
    const other = vm.categories.find(c => c.key === 'other')
    expect(other).toBeUndefined()
    expect(vm.totals.total).toBe(64)
  })
})
