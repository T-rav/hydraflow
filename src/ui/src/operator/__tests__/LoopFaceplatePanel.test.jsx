import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LoopFaceplatePanel } from '../LoopFaceplatePanel'
import {
  MODE_AUTO,
  MODE_AWAITING_TICK,
  MODE_NOT_ENGAGED,
  MODE_QUIESCENT,
  MODE_UNCONVERTED,
} from '../model/loopFaceplates'

// Component tests pass VM literals, never raw payloads — mirroring the
// FinderFaceplatePanel / SupervisorPanel component-test pattern.

function row(overrides = {}) {
  return {
    workerName: 'gate_health',
    controlClass: 'convertible',
    pvLabel: 'fleet pass rate',
    finderId: '',
    floorSigma: null,
    intervalS: null,
    setpoint: {
      value: 0.9, band: 0.05, units: 'fraction', direction: 'above',
      signed: false, signedBy: null, signedDate: null, authority: '#10824',
    },
    live: { pv: null, quiescent: null, setpointActive: null, lastRunTs: null, enabled: true },
    mode: MODE_UNCONVERTED,
    dueAt: null,
    overdue: false,
    ...overrides,
  }
}

function vm(overrides = {}) {
  return {
    total: 2,
    regulatingCount: 0,
    awaitingCount: 0,
    signedCount: 0,
    headerLabel: '2 loops · 1 convertible · 0 regulating',
    byClass: { convertible: 1, error_driven: 0, exploratory: 1, infrastructure: 0 },
    rows: [row()],
    ...overrides,
  }
}

describe('LoopFaceplatePanel', () => {
  it('renders the header label and a regulator row with its setpoint', () => {
    render(<LoopFaceplatePanel faceplates={vm()} />)
    expect(screen.getByTestId('loop-faceplate-header')).toHaveTextContent(
      '2 loops · 1 convertible · 0 regulating',
    )
    expect(screen.getByTestId('loop-faceplate-row-gate_health')).toBeInTheDocument()
    expect(screen.getByTestId('loop-faceplate-setpoint-gate_health')).toHaveTextContent(
      '0.9 ±0.05 fraction',
    )
  })

  it('an unsigned setpoint shows the unsigned badge — visible but inert', () => {
    render(<LoopFaceplatePanel faceplates={vm()} />)
    expect(screen.getByTestId('loop-faceplate-unsigned-gate_health')).toHaveTextContent(
      'unsigned',
    )
  })

  it('a signed setpoint shows the signer instead', () => {
    const signed = row({
      setpoint: {
        value: 0.9, band: 0.05, units: 'fraction', direction: 'above',
        signed: true, signedBy: 'travis', authority: '#10824',
      },
    })
    render(<LoopFaceplatePanel faceplates={vm({ rows: [signed] })} />)
    expect(screen.getByTestId('loop-faceplate-signed-gate_health')).toHaveTextContent(
      'signed: travis',
    )
    expect(screen.queryByTestId('loop-faceplate-unsigned-gate_health')).toBe(null)
  })

  it('an unconverted loop renders the neutral — lamp and a — pv, never zero', () => {
    render(<LoopFaceplatePanel faceplates={vm()} />)
    expect(screen.getByTestId('loop-faceplate-mode-gate_health')).toHaveTextContent('—')
    expect(screen.getByTestId('loop-faceplate-pv-gate_health')).toHaveTextContent('—')
  })

  it('QUIESCENT renders as its own lamp — a correct state, not a fault', () => {
    const quiet = row({
      mode: MODE_QUIESCENT,
      live: { pv: 0.97, quiescent: true, setpointActive: true, lastRunTs: null, enabled: true },
    })
    render(<LoopFaceplatePanel faceplates={vm({ rows: [quiet], regulatingCount: 1 })} />)
    expect(screen.getByTestId('loop-faceplate-mode-gate_health')).toHaveTextContent('QUIESCENT')
    expect(screen.getByTestId('loop-faceplate-pv-gate_health')).toHaveTextContent('0.97')
  })

  it('AUTO renders when regulating and acting', () => {
    const acting = row({
      mode: MODE_AUTO,
      live: { pv: 0.8, quiescent: false, setpointActive: true, lastRunTs: null, enabled: true },
    })
    render(<LoopFaceplatePanel faceplates={vm({ rows: [acting] })} />)
    expect(screen.getByTestId('loop-faceplate-mode-gate_health')).toHaveTextContent('AUTO')
  })

  it('floor sigma renders only when calibrated', () => {
    const sensed = row({ floorSigma: 0.5 })
    render(<LoopFaceplatePanel faceplates={vm({ rows: [sensed] })} />)
    expect(screen.getByTestId('loop-faceplate-sigma-gate_health')).toHaveTextContent('0.5')
  })

  it('non-regulator classes fold into the census line, not rows', () => {
    const infra = row({ workerName: 'workspace_gc', controlClass: 'infrastructure', setpoint: null })
    render(<LoopFaceplatePanel faceplates={vm({ rows: [row(), infra] })} />)
    expect(screen.queryByTestId('loop-faceplate-row-workspace_gc')).toBe(null)
    expect(screen.getByTestId('loop-faceplate-census')).toHaveTextContent('1 exploratory')
  })

  it('an empty / failed feed renders the calm empty state', () => {
    render(<LoopFaceplatePanel />)
    expect(screen.getByTestId('loop-faceplate-empty')).toBeInTheDocument()
  })
})

// #11232: a signed setpoint whose loop hasn't ticked since signing renders
// an explicit intermediate state — SIGNED lamp + awaiting-tick due caption —
// instead of the blank mode lamp that read "signing didn't take" for up to a
// weekly cadence.
describe('LoopFaceplatePanel — awaiting tick (#11232)', () => {
  const NOW = Date.parse('2026-08-15T04:20:00Z')

  function awaitingRow(overrides = {}) {
    return row({
      intervalS: 604800,
      mode: MODE_AWAITING_TICK,
      dueAt: '2026-08-21T05:34:00.000Z',
      overdue: false,
      setpoint: {
        value: 0.9, band: 0.05, units: 'fraction', direction: 'above',
        signed: true, signedBy: 'travis', signedDate: '2026-08-15', authority: '#10824',
      },
      live: { pv: null, quiescent: null, setpointActive: false, lastRunTs: '2026-08-14T05:34:00Z', enabled: true },
      ...overrides,
    })
  }

  it('renders the SIGNED lamp and a due caption with date + relative wait', () => {
    render(<LoopFaceplatePanel faceplates={vm({ rows: [awaitingRow()], awaitingCount: 1 })} now={NOW} />)
    expect(screen.getByTestId('loop-faceplate-mode-gate_health')).toHaveTextContent('SIGNED')
    expect(screen.getByTestId('loop-faceplate-due-gate_health')).toHaveTextContent(
      'awaiting tick · due 2026-08-21 · in 6d',
    )
  })

  it('renders overdue when the due instant has passed', () => {
    render(
      <LoopFaceplatePanel
        faceplates={vm({ rows: [awaitingRow({ overdue: true })], awaitingCount: 1 })}
        now={Date.parse('2026-08-22T00:00:00Z')}
      />,
    )
    expect(screen.getByTestId('loop-faceplate-due-gate_health')).toHaveTextContent('overdue')
  })

  it('renders "due unknown" honestly when the cadence is unknown', () => {
    render(
      <LoopFaceplatePanel faceplates={vm({ rows: [awaitingRow({ dueAt: null })], awaitingCount: 1 })} now={NOW} />,
    )
    expect(screen.getByTestId('loop-faceplate-due-gate_health')).toHaveTextContent(
      'awaiting tick · due unknown',
    )
  })

  it('NOT ENGAGED renders its own fault lamp when a post-signing tick did not engage', () => {
    const stuck = row({
      intervalS: 604800,
      mode: MODE_NOT_ENGAGED,
      setpoint: {
        value: 0.9, band: 0.05, units: 'fraction', direction: 'above',
        signed: true, signedBy: 'travis', signedDate: '2026-08-15', authority: '#10824',
      },
      live: { pv: 0.94, quiescent: false, setpointActive: false, lastRunTs: '2026-08-16T05:34:00Z', enabled: true },
    })
    render(<LoopFaceplatePanel faceplates={vm({ rows: [stuck] })} now={NOW} />)
    expect(screen.getByTestId('loop-faceplate-mode-gate_health')).toHaveTextContent('NOT ENGAGED')
    expect(screen.queryByTestId('loop-faceplate-due-gate_health')).toBe(null)
  })

  it('offers run now on a signed-but-awaiting row and reports the worker name', () => {
    const onRunNow = vi.fn()
    render(
      <LoopFaceplatePanel
        faceplates={vm({ rows: [awaitingRow()], awaitingCount: 1 })}
        now={NOW}
        onRunNow={onRunNow}
      />,
    )
    fireEvent.click(screen.getByTestId('loop-faceplate-run-gate_health'))
    expect(onRunNow).toHaveBeenCalledWith('gate_health')
  })

  it('an engaged (auto/quiescent) row offers no run-now button', () => {
    const engaged = awaitingRow({
      mode: MODE_AUTO,
      dueAt: null,
      live: { pv: 0.8, quiescent: false, setpointActive: true, lastRunTs: '2026-08-16T05:34:00Z', enabled: true },
    })
    render(<LoopFaceplatePanel faceplates={vm({ rows: [engaged] })} now={NOW} />)
    expect(screen.queryByTestId('loop-faceplate-run-gate_health')).toBe(null)
  })
})
