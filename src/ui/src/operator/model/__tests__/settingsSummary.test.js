import { describe, it, expect } from 'vitest'
import { toSettingsSummary } from '../settingsSummary'

// toSettingsSummary (epic #10556 follow-up) is a pure transform of the
// `/api/control/status` `config` slice into the operator console's
// at-a-glance settings view model. Field names mirror the backend
// ControlStatusConfig model.

function config(over = {}) {
  return {
    model: 'claude-opus-4-8',
    max_workers: 5,
    max_planners: 2,
    max_reviewers: 3,
    batch_size: 5,
    queue_strategy: 'weighted_mix',
    merge_policy_enabled: true,
    // A couple of unrelated fields the adapter must ignore.
    repo: 'owner/repo',
    app_version: '1.2.3',
    ...over,
  }
}

describe('toSettingsSummary', () => {
  it('extracts the key runtime settings as raw values', () => {
    const s = toSettingsSummary(config())
    expect(s.model).toBe('claude-opus-4-8')
    expect(s.maxWorkers).toBe(5)
    expect(s.maxPlanners).toBe(2)
    expect(s.maxReviewers).toBe(3)
    expect(s.batchSize).toBe(5)
    expect(s.queueStrategy).toBe('weighted_mix')
    expect(s.mergePolicy).toBe(true)
  })

  it('renders one display item per key setting', () => {
    const s = toSettingsSummary(config())
    const byKey = Object.fromEntries(s.items.map(i => [i.key, i]))
    expect(Object.keys(byKey).sort()).toEqual(
      ['batch', 'merge', 'model', 'planners', 'queue', 'reviewers', 'workers'],
    )
    expect(byKey.model).toEqual({ key: 'model', label: 'Model', value: 'claude-opus-4-8' })
    expect(byKey.workers.value).toBe('5')
    expect(byKey.queue.value).toBe('weighted_mix')
  })

  it('renders the merge policy toggle as on/off', () => {
    const on = Object.fromEntries(toSettingsSummary(config({ merge_policy_enabled: true })).items.map(i => [i.key, i]))
    const off = Object.fromEntries(toSettingsSummary(config({ merge_policy_enabled: false })).items.map(i => [i.key, i]))
    expect(on.merge.value).toBe('on')
    expect(off.merge.value).toBe('off')
  })

  it('handles a null config gracefully with placeholders', () => {
    const s = toSettingsSummary(null)
    expect(s.model).toBeNull()
    expect(s.maxWorkers).toBeNull()
    expect(s.mergePolicy).toBeNull()
    // Every item still renders, with the em-dash placeholder for absent values.
    expect(s.items).toHaveLength(7)
    for (const item of s.items) {
      expect(item.value).toBe('—')
    }
  })

  it('handles an empty / partial config without throwing', () => {
    const s = toSettingsSummary({})
    expect(s.items.map(i => i.value)).toEqual(['—', '—', '—', '—', '—', '—', '—'])

    const partial = toSettingsSummary({ model: 'sonnet', max_workers: 3 })
    const byKey = Object.fromEntries(partial.items.map(i => [i.key, i]))
    expect(byKey.model.value).toBe('sonnet')
    expect(byKey.workers.value).toBe('3')
    expect(byKey.queue.value).toBe('—')
    expect(byKey.merge.value).toBe('—')
  })

  it('renders a zero worker pool as "0", not a placeholder', () => {
    const byKey = Object.fromEntries(toSettingsSummary(config({ max_workers: 0 })).items.map(i => [i.key, i]))
    expect(byKey.workers.value).toBe('0')
  })

  it('is pure: deterministic and non-mutating', () => {
    const input = Object.freeze(config())
    const a = toSettingsSummary(input)
    const b = toSettingsSummary(input)
    expect(a).toEqual(b)
    // A frozen input proves no in-place mutation is attempted.
    expect(() => toSettingsSummary(input)).not.toThrow()
    expect(input.model).toBe('claude-opus-4-8')
  })
})
