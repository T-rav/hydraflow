import { describe, it, expect } from 'vitest'
import { toCostByRepo, EMPTY_COST_VM } from '../model/cost'

// `toCostByRepo` (#10785) is the PURE adapter for the
// /api/diagnostics/cost/by-model-by-repo payload: repo + per-repo
// cost-per-model over a rolling 24h window. No fetch, no React.

const payload = () => ({
  generated_at: '2026-08-01T00:00:00+00:00',
  window_hours: 24,
  window_label: 'last 24h',
  total_cost_usd: 3.5,
  all: [
    { model: 'claude-sonnet-4-6', cost_usd: 3.0, cost_unknown: false, calls: 2, input_tokens: 300, output_tokens: 150 },
    { model: 'claude-haiku-4-5', cost_usd: 0.5, cost_unknown: false, calls: 1, input_tokens: 40, output_tokens: 20 },
  ],
  repos: [
    {
      repo: 'org-b',
      total_cost_usd: 2.5,
      by_model: [
        { model: 'claude-sonnet-4-6', cost_usd: 2.0, cost_unknown: false, calls: 1, input_tokens: 200, output_tokens: 100 },
        { model: 'claude-haiku-4-5', cost_usd: 0.5, cost_unknown: false, calls: 1, input_tokens: 40, output_tokens: 20 },
      ],
    },
    {
      repo: 'org-a',
      total_cost_usd: 1.0,
      by_model: [
        { model: 'claude-sonnet-4-6', cost_usd: 1.0, cost_unknown: false, calls: 1, input_tokens: 100, output_tokens: 50 },
      ],
    },
  ],
})

describe('toCostByRepo — aggregate + per-repo shaping', () => {
  it('exposes the window label and total spend', () => {
    const vm = toCostByRepo(payload())
    expect(vm.windowLabel).toBe('last 24h')
    expect(vm.totalCostUsd).toBe(3.5)
    expect(vm.totalCostUnknown).toBe(false)
  })

  it('maps the aggregate rows, spend-descending, into ModelRows', () => {
    const vm = toCostByRepo(payload())
    expect(vm.all.map(r => r.model)).toEqual(['claude-sonnet-4-6', 'claude-haiku-4-5'])
    const sonnet = vm.all[0]
    expect(sonnet).toMatchObject({ costUsd: 3.0, calls: 2, tokensIn: 300, tokensOut: 150, costUnknown: false })
  })

  it('keeps the per-repo breakdown, sorted by repo spend descending', () => {
    const vm = toCostByRepo(payload())
    expect(vm.repos.map(r => r.repo)).toEqual(['org-b', 'org-a'])
    expect(vm.repos[0]).toMatchObject({ repo: 'org-b', totalCostUsd: 2.5 })
    expect(vm.repos[0].byModel.map(m => m.model)).toEqual(['claude-sonnet-4-6', 'claude-haiku-4-5'])
  })

  it('marks the total unknown when any aggregate model is unpriced (#9821)', () => {
    const raw = payload()
    raw.all[1].cost_unknown = true
    const vm = toCostByRepo(raw)
    expect(vm.totalCostUnknown).toBe(true)
    expect(vm.all.find(r => r.model === 'claude-haiku-4-5').costUnknown).toBe(true)
  })

  it('derives a missing repo total from its own rows', () => {
    const raw = payload()
    delete raw.repos[1].total_cost_usd
    const vm = toCostByRepo(raw)
    const orgA = vm.repos.find(r => r.repo === 'org-a')
    expect(orgA.totalCostUsd).toBe(1.0)
  })

  it('returns the EMPTY view model for a missing / malformed payload (never throws)', () => {
    expect(toCostByRepo(null)).toBe(EMPTY_COST_VM)
    expect(toCostByRepo(undefined)).toBe(EMPTY_COST_VM)
    expect(toCostByRepo('nope')).toBe(EMPTY_COST_VM)
  })

  it('tolerates absent all/repos arrays as empties', () => {
    const vm = toCostByRepo({ window_label: 'last 24h' })
    expect(vm.all).toEqual([])
    expect(vm.repos).toEqual([])
    expect(vm.totalCostUsd).toBe(0)
  })
})
