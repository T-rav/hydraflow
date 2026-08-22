import { describe, it, expect } from 'vitest'
import { toFinderFaceplates, EMPTY_FINDER_FACEPLATES_VM } from '../model/finderFaceplates'

// `toFinderFaceplates` (#10826) is the PURE adapter for the
// /api/diagnostics/finder-faceplates payload: one row per generative finder,
// each finder's measured noise floor joined against its live finding-rate. No
// fetch, no React. Fixtures mirror the real endpoint rows.

const payload = () => ({
  generated_at: '2026-08-03T00:00:00+00:00',
  finders: [
    // Uncalibrated (deferred LLM) finder — identity + pending only.
    { finder_id: 'erosion_metrics', signal_class: 'erosion', calibrated: false, live_rate: null, status: 'uncalibrated' },
    // Clean calibrated finder above its floor (vetted baseline, non-zero sigma).
    {
      finder_id: 'edge_proposer', signal_class: 'edges', calibrated: true, live_rate: 41,
      status: 'above_floor', floor_mean: 39.0, floor_sigma: 1.5, threshold: 39, sample_count: 5,
      low_confidence: false, last_calibrated: '2026-08-01T00:00:00+00:00', drift_days: 2,
      baseline_stale: false, baseline_sha: 'abc1234', baseline_vetted: true,
    },
    // Deterministic zero-noise floor, live rate exactly 0 → within floor.
    {
      finder_id: 'entry_evidence', signal_class: 'wiki-evidence', calibrated: true, live_rate: 0,
      status: 'within_floor', floor_mean: 0.0, floor_sigma: 0.0, threshold: 0, sample_count: 4,
      low_confidence: false, last_calibrated: '2026-08-01T00:00:00+00:00', drift_days: 0,
      baseline_stale: false, baseline_sha: 'def5678', baseline_vetted: true,
    },
    // Low-confidence, UNVETTED baseline, unknown staleness → provisional.
    {
      finder_id: 'wiki_rot', signal_class: 'wiki-rot', calibrated: true, live_rate: 18,
      status: 'above_floor', floor_mean: 15.0, floor_sigma: 0.0, threshold: 15, sample_count: 2,
      low_confidence: true, last_calibrated: '2026-08-01T00:00:00+00:00', drift_days: 0,
      baseline_stale: null, baseline_sha: 'b653fca', baseline_vetted: false,
    },
  ],
})

describe('toFinderFaceplates — calibrated/pending split + header counts', () => {
  it('splits calibrated finders from pending (uncalibrated) ones, preserving order', () => {
    const vm = toFinderFaceplates(payload())
    expect(vm.calibrated.map(r => r.finderId)).toEqual(['edge_proposer', 'entry_evidence', 'wiki_rot'])
    expect(vm.pending.map(r => r.finderId)).toEqual(['erosion_metrics'])
  })

  it('derives the glanceable header count ("N of M calibrated; K above floor")', () => {
    const vm = toFinderFaceplates(payload())
    expect(vm.total).toBe(4)
    expect(vm.calibratedCount).toBe(3)
    expect(vm.aboveFloorCount).toBe(2)
    expect(vm.headerLabel).toBe('3 of 4 calibrated; 2 above floor')
  })
})

describe('toFinderFaceplates — per-row normalization', () => {
  it('renders a zero-sigma floor as "±0 deterministic" and a noisy floor as "mean ± sigma"', () => {
    const vm = toFinderFaceplates(payload())
    const wikiRot = vm.calibrated.find(r => r.finderId === 'wiki_rot')
    const edge = vm.calibrated.find(r => r.finderId === 'edge_proposer')
    expect(wikiRot.floorLabel).toBe('15 ±0 deterministic')
    expect(edge.floorLabel).toBe('39 ± 1.5')
  })

  it('preserves a genuine live_rate of 0 as 0, and a null live_rate as null (never 0-for-null)', () => {
    const vm = toFinderFaceplates(payload())
    expect(vm.calibrated.find(r => r.finderId === 'entry_evidence').liveRate).toBe(0)
    expect(vm.pending.find(r => r.finderId === 'erosion_metrics').liveRate).toBeNull()
  })

  it('keeps a calibrated row with no live-rate source as null (count never invented)', () => {
    const raw = payload()
    raw.finders[1].live_rate = null // edge_proposer: floor but no live rate
    const vm = toFinderFaceplates(raw)
    const edge = vm.calibrated.find(r => r.finderId === 'edge_proposer')
    expect(edge.liveRate).toBeNull()
    expect(edge.label).toContain('no live rate')
  })

  it('flags a floor as provisional when low_confidence OR the baseline is unvetted', () => {
    const vm = toFinderFaceplates(payload())
    // wiki_rot: low_confidence true AND baseline_vetted false.
    expect(vm.calibrated.find(r => r.finderId === 'wiki_rot').provisional).toBe(true)
    // edge_proposer: confident + vetted → not provisional.
    expect(vm.calibrated.find(r => r.finderId === 'edge_proposer').provisional).toBe(false)
  })

  it('treats a confident-but-unvetted baseline as provisional on its own', () => {
    const raw = payload()
    raw.finders[1].low_confidence = false
    raw.finders[1].baseline_vetted = false // vetted flips false while confidence stays
    const vm = toFinderFaceplates(raw)
    expect(vm.calibrated.find(r => r.finderId === 'edge_proposer').provisional).toBe(true)
  })

  it('marks a row stale only when baseline_stale is explicitly true (null → not stale)', () => {
    const vm = toFinderFaceplates(payload())
    expect(vm.calibrated.find(r => r.finderId === 'wiki_rot').stale).toBe(false) // baseline_stale null
    const raw = payload()
    raw.finders[3].baseline_stale = true
    const stale = toFinderFaceplates(raw).calibrated.find(r => r.finderId === 'wiki_rot')
    expect(stale.stale).toBe(true)
    expect(stale.baselineStale).toBe(true)
  })

  it('gives a pending finder the calm label and no floor fields', () => {
    const vm = toFinderFaceplates(payload())
    const erosion = vm.pending[0]
    expect(erosion.calibrated).toBe(false)
    expect(erosion.status).toBe('uncalibrated')
    expect(erosion.label).toBe('pending — run calibration')
    expect(erosion.floorLabel).toBeUndefined()
    expect(erosion.threshold).toBeUndefined()
  })
})

describe('toFinderFaceplates — malformed / empty payloads', () => {
  it('returns the frozen EMPTY view model for a missing / malformed payload (never throws)', () => {
    expect(toFinderFaceplates(null)).toBe(EMPTY_FINDER_FACEPLATES_VM)
    expect(toFinderFaceplates(undefined)).toBe(EMPTY_FINDER_FACEPLATES_VM)
    expect(toFinderFaceplates('nope')).toBe(EMPTY_FINDER_FACEPLATES_VM)
    expect(toFinderFaceplates({ finders: [] })).toBe(EMPTY_FINDER_FACEPLATES_VM)
  })

  it('exposes a calm empty header on the EMPTY VM', () => {
    expect(EMPTY_FINDER_FACEPLATES_VM.headerLabel).toBe('no finders')
    expect(EMPTY_FINDER_FACEPLATES_VM.calibrated).toEqual([])
    expect(EMPTY_FINDER_FACEPLATES_VM.pending).toEqual([])
  })

  it('accepts a bare array payload as well as the {finders} envelope', () => {
    const vm = toFinderFaceplates(payload().finders)
    expect(vm.total).toBe(4)
    expect(vm.calibratedCount).toBe(3)
  })

  it('skips non-object rows without throwing', () => {
    const vm = toFinderFaceplates({ finders: [null, 'x', payload().finders[1]] })
    expect(vm.total).toBe(1)
    expect(vm.calibrated.map(r => r.finderId)).toEqual(['edge_proposer'])
  })
})
