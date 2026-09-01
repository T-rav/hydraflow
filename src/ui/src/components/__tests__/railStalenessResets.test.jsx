/**
 * #11924 — escape `sampled-audit:11403:0bae96175dde`.
 *
 * The rail carries TWO independent staleness signals and neither implies the
 * other. #11414 cleared `pipelineSnapshotAt` at the three sites that empty the
 * rail outside the authoritative-snapshot path, which repaired OperatorConsole
 * (it reads the stamp) and did nothing for StreamView, which read
 * `pipelineSnapshotReady` — a flag defaulting true that no reset path touches.
 * The main console kept rendering the confidently-empty rail #11350 exists to
 * prevent, one component over.
 *
 * These drive the REAL reducer and the REAL StreamView: the reset paths are
 * reducer transitions and the symptom is a render, so a test that stubbed
 * either would be asserting its own fixture.
 *
 * Stated over the RENDERED badge rather than over a flag, so they hold under
 * either accepted remedy — the reducer also clearing the flag, or the consumer
 * deriving from the stamp.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { reducer, initialState } = await import('../../context/HydraFlowContext')
const { StreamView } = await import('../StreamView')

// Wall-clock "now": the stamp is compared against Date.now(), so a fixed epoch
// would make the fresh-rail control stale for a fixture reason rather than a
// real one.
const NOW = Date.now()

/** A rail that has been authoritatively snapshotted AND has cards in it. */
const seeded = () =>
  reducer(initialState, {
    type: 'PIPELINE_SNAPSHOT',
    data: { plan: [{ number: 1, title: 'seeded' }] },
    at: NOW,
  })

const railIsEmpty = (state) =>
  Object.values(state.pipelineIssues).every((issues) => (issues?.length || 0) === 0)

function mount(state) {
  mockUseHydraFlow.mockReturnValue({
    pipelineIssues: state.pipelineIssues,
    prs: [],
    stageStatus: {},
    workers: {},
    config: {},
    pipelineSnapshotReady: state.pipelineSnapshotReady,
    pipelineSnapshotAt: state.pipelineSnapshotAt,
  })
  render(
    <StreamView
      intents={[]}
      expandedStages={{}}
      onToggleStage={() => {}}
      onRequestChanges={() => {}}
    />,
  )
}

const badge = () => screen.queryByTestId('pipeline-resyncing-badge')

/** Every reducer branch that empties the rail outside the snapshot path. */
const RESET_ACTIONS = {
  'session reset': { type: 'SESSION_RESET' },
  'repo switch': { type: 'SELECT_REPO', data: { slug: 'owner/other' } },
  'orchestrator session start': {
    type: 'orchestrator_status',
    data: { status: 'running', reset: true },
  },
}

beforeEach(() => {
  cleanup()
  mockUseHydraFlow.mockReset()
})

describe('#11924 / rail staleness on every reset path', () => {
  // Parametrised over the reset table itself: a fourth branch that empties the
  // rail is covered by adding it to RESET_ACTIONS, not by remembering to write
  // a fourth test. Two of these three were never exercised before.
  for (const [name, action] of Object.entries(RESET_ACTIONS)) {
    it(`${name} never renders a confidently-empty rail`, () => {
      const state = reducer(seeded(), action)

      expect(railIsEmpty(state)).toBe(true)
      mount(state)
      expect(badge()).not.toBeNull()
    })
  }

  it('every reset path still clears the #11414 freshness stamp', () => {
    for (const action of Object.values(RESET_ACTIONS)) {
      const state = reducer(seeded(), action)
      expect(state.pipelineSnapshotAt).toBeNull()
    }
  })
})

describe('#11924 / controls — a remedy that breaks one has over-corrected', () => {
  it('an authoritative populated snapshot is presented as truth', () => {
    const state = seeded()

    expect(railIsEmpty(state)).toBe(false)
    mount(state)
    expect(badge()).toBeNull()
  })

  it('a not-ready snapshot over a populated rail still warns (#11279)', () => {
    const state = reducer(seeded(), {
      type: 'PIPELINE_SNAPSHOT',
      data: { plan: [] },
      ready: false,
      at: NOW,
    })

    mount(state)
    expect(badge()).not.toBeNull()
  })
})
