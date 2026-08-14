import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LoopFaceplatePanel } from '../LoopFaceplatePanel'
import {
  MODE_AUTO,
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
    setpoint: {
      value: 0.9, band: 0.05, units: 'fraction', direction: 'above',
      signed: false, signedBy: null, authority: '#10824',
    },
    live: { pv: null, quiescent: null, setpointActive: null, lastRunTs: null, enabled: true },
    mode: MODE_UNCONVERTED,
    ...overrides,
  }
}

function vm(overrides = {}) {
  return {
    total: 2,
    regulatingCount: 0,
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
