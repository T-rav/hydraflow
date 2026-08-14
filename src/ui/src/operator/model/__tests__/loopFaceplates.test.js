import { describe, it, expect } from 'vitest'
import {
  EMPTY_LOOP_FACEPLATES_VM,
  MODE_AUTO,
  MODE_QUIESCENT,
  MODE_UNCONVERTED,
  toLoopFaceplates,
} from '../loopFaceplates'

// #10826 view-model: joins the static register payload against the live
// backgroundWorkers WS slice. Honesty contracts: absent regulator keys →
// unconverted with pv null (never zero); unsigned setpoints stay visible but
// marked; malformed payloads → the frozen EMPTY VM.

function staticRow(overrides = {}) {
  return {
    worker_name: 'gate_health',
    control_class: 'convertible',
    pv_label: 'fleet pass rate',
    finder_id: '',
    floor_sigma: null,
    setpoint: {
      value: 0.9, band: 0.05, units: 'fraction', direction: 'above',
      signed: false, signed_by: null, authority: '#10824',
    },
    ...overrides,
  }
}

function payload(rows, counts = {}) {
  return {
    generated_at: '2026-08-13T00:00:00+00:00',
    counts: { convertible: 1, error_driven: 0, exploratory: 0, infrastructure: 0, ...counts },
    loops: rows,
  }
}

describe('toLoopFaceplates — join + honesty', () => {
  it('malformed / empty payloads yield the frozen EMPTY VM', () => {
    expect(toLoopFaceplates(null, [])).toBe(EMPTY_LOOP_FACEPLATES_VM)
    expect(toLoopFaceplates({}, [])).toBe(EMPTY_LOOP_FACEPLATES_VM)
    expect(toLoopFaceplates({ loops: [] }, [])).toBe(EMPTY_LOOP_FACEPLATES_VM)
    expect(toLoopFaceplates('nope', [])).toBe(EMPTY_LOOP_FACEPLATES_VM)
  })

  it('a worker with live regulator keys joins to mode auto/quiescent', () => {
    const workers = [
      {
        name: 'gate_health',
        last_run: '2026-08-13T01:00:00Z',
        enabled: true,
        details: { pv_pass_rate: 0.97, setpoint_active: true, quiescent: true },
      },
    ]
    const vm = toLoopFaceplates(payload([staticRow()]), workers)
    const row = vm.rows[0]
    expect(row.live.pv).toBe(0.97)
    expect(row.mode).toBe(MODE_QUIESCENT)
    expect(vm.regulatingCount).toBe(1)

    workers[0].details.quiescent = false
    const acting = toLoopFaceplates(payload([staticRow()]), workers)
    expect(acting.rows[0].mode).toBe(MODE_AUTO)
  })

  it('absent regulator keys mean unconverted with pv null — never zero', () => {
    const workers = [
      { name: 'gate_health', last_run: null, enabled: true, details: { findings: 3 } },
    ]
    const row = toLoopFaceplates(payload([staticRow()]), workers).rows[0]
    expect(row.mode).toBe(MODE_UNCONVERTED)
    expect(row.live.pv).toBe(null)
    expect(row.live.quiescent).toBe(null)
    expect(row.live.setpointActive).toBe(null)
  })

  it('a loop with no live worker at all joins to unconverted nulls', () => {
    const row = toLoopFaceplates(payload([staticRow()]), []).rows[0]
    expect(row.mode).toBe(MODE_UNCONVERTED)
    expect(row.live.pv).toBe(null)
    expect(row.live.lastRunTs).toBe(null)
    expect(row.live.enabled).toBe(null)
  })

  it('unsigned setpoints stay visible and marked unsigned', () => {
    const row = toLoopFaceplates(payload([staticRow()]), []).rows[0]
    expect(row.setpoint.signed).toBe(false)
    expect(row.setpoint.signedBy).toBe(null)
    expect(row.setpoint.value).toBe(0.9)
  })

  it('signed setpoints carry the signer and count in the header math', () => {
    const signed = staticRow({
      setpoint: {
        value: 0.9, band: 0.05, units: 'fraction', direction: 'above',
        signed: true, signed_by: 'travis', authority: '#10824',
      },
    })
    const vm = toLoopFaceplates(payload([signed]), [])
    expect(vm.rows[0].setpoint.signed).toBe(true)
    expect(vm.rows[0].setpoint.signedBy).toBe('travis')
    expect(vm.signedCount).toBe(1)
    // Signed but the loop isn't reporting regulator keys → not regulating.
    expect(vm.regulatingCount).toBe(0)
  })

  it('header label reads from counts + live regulating state', () => {
    const workers = [
      {
        name: 'gate_health',
        details: { pv_pass_rate: 0.97, setpoint_active: true, quiescent: true },
      },
    ]
    const vm = toLoopFaceplates(
      payload([staticRow(), staticRow({ worker_name: 'workspace_gc', control_class: 'infrastructure', setpoint: null })], { infrastructure: 1 }),
      workers,
    )
    expect(vm.total).toBe(2)
    expect(vm.headerLabel).toBe('2 loops · 1 convertible · 1 regulating')
  })

  it('floor sigma preserved as number or null', () => {
    const withSigma = staticRow({ worker_name: 'wiki_rot_detector', floor_sigma: 0.5 })
    const vm = toLoopFaceplates(payload([withSigma, staticRow()]), [])
    const by = Object.fromEntries(vm.rows.map(r => [r.workerName, r]))
    expect(by.wiki_rot_detector.floorSigma).toBe(0.5)
    expect(by.gate_health.floorSigma).toBe(null)
  })
})
