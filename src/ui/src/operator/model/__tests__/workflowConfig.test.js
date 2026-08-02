import { describe, it, expect } from 'vitest'
import { toWorkflowConfig, SECTION_ORDER, OTHER_SECTION } from '../workflowConfig'

// toWorkflowConfig (#10786) is a pure transform of the settings-schema rows
// (GET /api/control/settings-schema) into ordered, non-empty workflow sections
// for the operator console's WorkflowConfigPanel.

function row(name, section, over = {}) {
  return { name, section, group: section, type: 'int', value: 1, ...over }
}

describe('toWorkflowConfig', () => {
  it('buckets rows into sections in declared display order', () => {
    // Deliberately out of order on input; output follows SECTION_ORDER.
    const out = toWorkflowConfig([
      row('a', 'Safety & Reliability'),
      row('b', 'Work Queue'),
      row('c', 'Workers & Batch'),
    ])
    expect(out.map((s) => s.section)).toEqual([
      'Work Queue',
      'Workers & Batch',
      'Safety & Reliability',
    ])
  })

  it('preserves incoming row order within a section', () => {
    const out = toWorkflowConfig([
      row('max_triagers', 'Workers & Batch'),
      row('max_workers', 'Workers & Batch'),
      row('batch_size', 'Workers & Batch'),
    ])
    expect(out).toHaveLength(1)
    expect(out[0].rows.map((r) => r.name)).toEqual([
      'max_triagers',
      'max_workers',
      'batch_size',
    ])
  })

  it('omits sections with no rows', () => {
    const out = toWorkflowConfig([row('a', 'Work Queue')])
    expect(out.map((s) => s.section)).toEqual(['Work Queue'])
  })

  it('routes a missing/blank/unknown section into Other (never dropped)', () => {
    const out = toWorkflowConfig([
      row('none', undefined),
      row('blank', '   '),
      row('known', 'Work Queue'),
    ])
    const other = out.find((s) => s.section === OTHER_SECTION)
    expect(other).toBeTruthy()
    expect(other.rows.map((r) => r.name).sort()).toEqual(['blank', 'none'])
  })

  it('is total: output field count equals input row count', () => {
    const rows = [
      row('a', 'Work Queue'),
      row('b', 'Workers & Batch'),
      row('c', undefined),
      row('d', 'Mystery Section'),
      row('e', 'Safety & Reliability'),
    ]
    const out = toWorkflowConfig(rows)
    const total = out.reduce((n, s) => n + s.rows.length, 0)
    expect(total).toBe(rows.length)
  })

  it('always renders Other last, even after unknown sections', () => {
    const out = toWorkflowConfig([
      row('x', OTHER_SECTION),
      row('y', 'Mystery Section'),
      row('z', 'Work Queue'),
    ])
    const names = out.map((s) => s.section)
    expect(names[0]).toBe('Work Queue')
    expect(names.indexOf('Mystery Section')).toBeLessThan(names.indexOf(OTHER_SECTION))
    expect(names[names.length - 1]).toBe(OTHER_SECTION)
  })

  it('returns empty for null / non-array / empty input without throwing', () => {
    expect(toWorkflowConfig(null)).toEqual([])
    expect(toWorkflowConfig(undefined)).toEqual([])
    expect(toWorkflowConfig('nope')).toEqual([])
    expect(toWorkflowConfig({})).toEqual([])
    expect(toWorkflowConfig([])).toEqual([])
  })

  it('skips non-object entries defensively', () => {
    const out = toWorkflowConfig([null, 42, row('ok', 'Work Queue'), undefined])
    expect(out).toHaveLength(1)
    expect(out[0].rows.map((r) => r.name)).toEqual(['ok'])
  })

  it('is pure: deterministic and non-mutating', () => {
    const input = Object.freeze([Object.freeze(row('a', 'Work Queue'))])
    const a = toWorkflowConfig(input)
    const b = toWorkflowConfig(input)
    expect(a).toEqual(b)
    expect(() => toWorkflowConfig(input)).not.toThrow()
  })

  it('exposes Other as the terminal entry of SECTION_ORDER', () => {
    expect(SECTION_ORDER[SECTION_ORDER.length - 1]).toBe(OTHER_SECTION)
  })
})
