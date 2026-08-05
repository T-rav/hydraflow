import { describe, it, expect } from 'vitest'
import { toJudgeCalibration, EMPTY_JUDGE_CALIBRATION_VM } from '../model/judgeCalibration'

// `toJudgeCalibration` (#10836) is the PURE adapter for the
// /api/diagnostics/judge-calibration payload: one row per review judge, each
// carrying its proper-scoring report — calibration (ECE) AND discrimination
// (AUC) reported as separate axes. No fetch, no React. Fixtures mirror the real
// endpoint rows (snake_case JudgeScore.to_json_dict()).

const payload = () => ({
  generated_at: '2026-08-04T00:00:00+00:00',
  resolved_total: 14,
  grace_window_days: 7,
  judges: [
    // Well-scored judge: calibrated + discriminating, enough resolved verdicts.
    {
      judge_id: 'post_verify', judge_family: 'review_advisor', n_resolved: 10,
      brier: 0.083333, log_score: 0.29, calibration_error: 0.05,
      calibration_bins: [{ bin_index: 8, mean_confidence: 0.9, empirical_rate: 0.9, n: 10 }],
      discrimination: 0.82, low_confidence: false, discrimination_undefined: false,
    },
    // Low-confidence judge: scored but too few resolved → provisional.
    {
      judge_id: 'precheck', judge_family: 'review_advisor', n_resolved: 2,
      brier: 0.25, log_score: 0.6, calibration_error: 0.2,
      calibration_bins: [], discrimination: 0.5,
      low_confidence: true, discrimination_undefined: false,
    },
    // AUC undefined: all resolved outcomes one class → discrimination has no meaning.
    {
      judge_id: 'mid_flight', judge_family: 'review_advisor', n_resolved: 4,
      brier: 0.1, log_score: 0.33, calibration_error: 0.08,
      calibration_bins: [], discrimination: null,
      low_confidence: false, discrimination_undefined: true,
    },
    // Pending judge: no resolved verdicts yet → null scores, awaiting state.
    {
      judge_id: 'consult', judge_family: 'review_advisor', n_resolved: 0,
      brier: null, log_score: null, calibration_error: null,
      calibration_bins: [], discrimination: null,
      low_confidence: false, discrimination_undefined: false,
    },
  ],
})

describe('toJudgeCalibration — scored/pending split + header counts', () => {
  it('splits scored judges from pending (unresolved) ones, in judgeId order', () => {
    const vm = toJudgeCalibration(payload())
    expect(vm.scored.map(r => r.judgeId)).toEqual(['mid_flight', 'post_verify', 'precheck'])
    expect(vm.pending.map(r => r.judgeId)).toEqual(['consult'])
  })

  it('derives the glanceable header count ("N of M scored · K resolved")', () => {
    const vm = toJudgeCalibration(payload())
    expect(vm.total).toBe(4)
    expect(vm.scoredCount).toBe(3)
    expect(vm.resolvedTotal).toBe(14)
    expect(vm.graceWindowDays).toBe(7)
    expect(vm.headerLabel).toBe('3 of 4 scored · 14 resolved')
  })

  it('falls back to summing per-judge n_resolved when resolved_total is absent', () => {
    const raw = payload()
    delete raw.resolved_total
    const vm = toJudgeCalibration(raw)
    expect(vm.resolvedTotal).toBe(16) // 10 + 2 + 4 + 0
  })
})

describe('toJudgeCalibration — per-row normalization', () => {
  it('keeps calibration (ECE) and discrimination (AUC) as separate rounded labels', () => {
    const vm = toJudgeCalibration(payload())
    const pv = vm.scored.find(r => r.judgeId === 'post_verify')
    expect(pv.calibrationLabel).toBe('0.05') // ECE
    expect(pv.discriminationLabel).toBe('0.82') // AUC
    expect(pv.brierLabel).toBe('0.083') // rounded to 3 decimals
  })

  it('renders AUC as "n/a" (never a fake 0.5) when discrimination is undefined', () => {
    const vm = toJudgeCalibration(payload())
    const mf = vm.scored.find(r => r.judgeId === 'mid_flight')
    expect(mf.discriminationUndefined).toBe(true)
    expect(mf.discrimination).toBeNull()
    expect(mf.discriminationLabel).toBe('n/a')
  })

  it('flags a scored judge as provisional when low_confidence (too few resolved)', () => {
    const vm = toJudgeCalibration(payload())
    expect(vm.scored.find(r => r.judgeId === 'precheck').provisional).toBe(true)
    expect(vm.scored.find(r => r.judgeId === 'post_verify').provisional).toBe(false)
  })

  it('gives a pending judge the calm label and no score fields', () => {
    const vm = toJudgeCalibration(payload())
    const consult = vm.pending[0]
    expect(consult.scored).toBe(false)
    expect(consult.status).toBe('pending')
    expect(consult.label).toBe('awaiting resolved verdicts')
    expect(consult.brierLabel).toBeUndefined()
    expect(consult.calibrationLabel).toBeUndefined()
  })

  it('treats a judge with resolved verdicts but a null brier as pending (no invented score)', () => {
    const raw = payload()
    raw.judges[0].brier = null // post_verify: has n_resolved but no computable score
    const vm = toJudgeCalibration(raw)
    expect(vm.scored.map(r => r.judgeId)).toEqual(['mid_flight', 'precheck'])
    expect(vm.pending.map(r => r.judgeId)).toEqual(['consult', 'post_verify'])
  })
})

describe('toJudgeCalibration — malformed / empty payloads', () => {
  it('returns the frozen EMPTY view model for a missing / malformed payload (never throws)', () => {
    expect(toJudgeCalibration(null)).toBe(EMPTY_JUDGE_CALIBRATION_VM)
    expect(toJudgeCalibration(undefined)).toBe(EMPTY_JUDGE_CALIBRATION_VM)
    expect(toJudgeCalibration('nope')).toBe(EMPTY_JUDGE_CALIBRATION_VM)
    expect(toJudgeCalibration({ judges: [] })).toBe(EMPTY_JUDGE_CALIBRATION_VM)
  })

  it('exposes a calm empty header on the EMPTY VM', () => {
    expect(EMPTY_JUDGE_CALIBRATION_VM.headerLabel).toBe('no judges')
    expect(EMPTY_JUDGE_CALIBRATION_VM.scored).toEqual([])
    expect(EMPTY_JUDGE_CALIBRATION_VM.pending).toEqual([])
  })

  it('accepts a bare array payload as well as the {judges} envelope', () => {
    const vm = toJudgeCalibration(payload().judges)
    expect(vm.total).toBe(4)
    expect(vm.scoredCount).toBe(3)
    // A bare array carries no envelope → resolved_total falls back to the row sum.
    expect(vm.resolvedTotal).toBe(16)
  })

  it('skips non-object rows without throwing', () => {
    const vm = toJudgeCalibration({ judges: [null, 'x', payload().judges[0]] })
    expect(vm.total).toBe(1)
    expect(vm.scored.map(r => r.judgeId)).toEqual(['post_verify'])
  })
})
