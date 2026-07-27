import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PIPELINE_STAGES } from '../../constants'
import { deriveStageStatus } from '../../hooks/useStageStatus'
import { STAGE_KEYS } from '../../hooks/useTimeline'

const mockUseHydraFlow = vi.fn()

// Mock only useHydraFlow; pass through the real module's other exports (e.g.
// workerKey, used by findWorkerTranscript) so they don't drift from the source.
vi.mock('../../context/HydraFlowContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { StreamView, toStreamIssue, findWorkerTranscript, TranscriptRow } = await import('../StreamView')

function defaultHydraFlowContext(overrides = {}) {
  const defaultPipeline = { triage: [], plan: [], implement: [], review: [], merged: [] }
  const pipelineIssues = overrides.pipelineIssues
    ? { ...defaultPipeline, ...overrides.pipelineIssues }
    : defaultPipeline
  const workers = overrides.workers || {}
  const backgroundWorkers = overrides.backgroundWorkers || []
  const config = overrides.config || { max_triagers: 1, max_planners: 2, max_workers: 3, max_reviewers: 2 }
  const pipelineStats = overrides.pipelineStats || null
  return {
    pipelineIssues,
    workers,
    prs: [],
    config,
    backgroundWorkers,
    stageStatus: deriveStageStatus(
      pipelineIssues,
      workers,
      backgroundWorkers,
      pipelineStats,
    ),
    ...overrides,
  }
}

const defaultHydraFlow = defaultHydraFlowContext()

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext())
})

// All stages open by default for test visibility
const allExpanded = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, true]))

const defaultProps = {
  intents: [],
  expandedStages: allExpanded,
  onToggleStage: () => {},
  onRequestChanges: () => {},
}

const basePipeIssue = {
  issue_number: 42,
  title: 'Test issue',
  url: 'https://github.com/test/42',
}

describe('HITL issues are rendered in the workstream (WS-RT)', () => {
  it('renders a card for an issue escalated to the hitl bucket', () => {
    // Before the fix PIPELINE_STAGES had no 'hitl' entry, so StreamView's
    // `PIPELINE_STAGES.map(...)` never rendered the hitl bucket — an escalated
    // issue vanished from the board entirely (present only in the HITL tab).
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        hitl: [{ issue_number: 77, title: 'Escalated issue', status: 'hitl' }],
      },
    }))
    render(<StreamView {...defaultProps} />)

    expect(screen.getByTestId('stage-section-hitl')).toBeTruthy()
    expect(screen.getByTestId('stream-card-77')).toBeTruthy()
    expect(screen.getByText('Escalated issue')).toBeTruthy()
  })

  it('labels the hitl bucket as needs-human, not merged, with a red dot', () => {
    // The hitl stage has role:null like merged, so it shares the worker-less
    // rendering branches. Those branches must stay stage-aware: a "Needs Human"
    // escalation bucket reading "merged" + green (success) is a mislabel.
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        hitl: [{ issue_number: 77, title: 'Escalated issue', status: 'hitl' }],
      },
    }))
    render(<StreamView {...defaultProps} />)

    const header = screen.getByTestId('stage-header-hitl')
    expect(header.textContent).not.toContain('merged')
    expect(header.textContent).toContain('needs human')

    const dot = screen.getByTestId('stage-dot-hitl')
    expect(dot.style.background).not.toBe('var(--green)')
    expect(dot.style.background).toBe('var(--red)')
  })
})

describe('StreamView stage indicators', () => {
  it('keeps stream card horizontal inset aligned with its stage header', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        review: [{ issue_number: 42, title: 'Review card', status: 'queued' }],
      },
    }))
    render(<StreamView {...defaultProps} />)

    const header = screen.getByTestId('stage-header-review')
    const card = screen.getByTestId('stream-card-42')

    expect(header.style.margin).toBe('8px 8px 4px')
    expect(card.style.margin).toBe('0px 8px 8px')
  })

  describe('Status dot colors', () => {
    it('shows green dot when stage has active workers', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        workers: {
          'triage-5': { status: 'evaluating', worker: 1, role: 'triage', title: 'Triage #5', branch: '', transcript: [], pr: null },
        },
        pipelineIssues: {
          triage: [{ issue_number: 5, title: 'Test', status: 'active' }],
          plan: [], implement: [], review: [],
        },
        pipelineStats: {
          stages: { triage: { worker_count: 1, active: 1, queued: 0 } },
        },
        backgroundWorkers: [
          { name: 'triage', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-triage')
      expect(dot.style.background).toBe('var(--green)')
    })

    it('shows yellow dot when stage is enabled but no active workers', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'plan', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-plan')
      expect(dot.style.background).toBe('var(--yellow)')
    })

    it('shows red dot when stage is disabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'implement', status: 'ok', enabled: false, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-implement')
      expect(dot.style.background).toBe('var(--red)')
    })

    it('defaults to enabled (yellow) when no backgroundWorkers entry exists', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [],
      }))
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-triage')
      expect(dot.style.background).toBe('var(--yellow)')
    })
  })

  describe('Disabled badge', () => {
    it('shows "Disabled" badge when stage is disabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'review', status: 'ok', enabled: false, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      expect(screen.getByTestId('stage-disabled-review')).toHaveTextContent('Disabled')
    })

    it('does not show "Disabled" badge when stage is enabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'review', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      expect(screen.queryByTestId('stage-disabled-review')).not.toBeInTheDocument()
    })
  })

  describe('Opacity dimming', () => {
    it('applies reduced opacity when stage is disabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'implement', status: 'ok', enabled: false, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const section = screen.getByTestId('stage-section-implement')
      expect(section.style.opacity).toBe('0.5')
    })

    it('has full opacity when stage is enabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'implement', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const section = screen.getByTestId('stage-section-implement')
      expect(section.style.opacity).toBe('1')
    })
  })

  describe('Merged stage dot', () => {
    it('renders green status dot for merged stage', () => {
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-merged')
      expect(dot).toBeInTheDocument()
      expect(dot.style.background).toBe('var(--green)')
    })
  })

  describe('Multiple stages with mixed states', () => {
    it('shows correct indicators for multiple stages simultaneously', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        workers: {
          'triage-5': { status: 'evaluating', worker: 1, role: 'triage', title: 'Triage #5', branch: '', transcript: [], pr: null },
        },
        pipelineStats: {
          stages: { triage: { worker_count: 1, active: 1, queued: 0 } },
        },
        backgroundWorkers: [
          { name: 'triage', status: 'ok', enabled: true, last_run: null, details: {} },
          { name: 'plan', status: 'ok', enabled: true, last_run: null, details: {} },
          { name: 'implement', status: 'ok', enabled: false, last_run: null, details: {} },
          { name: 'review', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      // Triage: enabled + active worker = green
      expect(screen.getByTestId('stage-dot-triage').style.background).toBe('var(--green)')
      // Plan: enabled + no workers = yellow
      expect(screen.getByTestId('stage-dot-plan').style.background).toBe('var(--yellow)')
      // Implement: disabled = red
      expect(screen.getByTestId('stage-dot-implement').style.background).toBe('var(--red)')
      // Review: enabled + no workers = yellow
      expect(screen.getByTestId('stage-dot-review').style.background).toBe('var(--yellow)')

      // Only implement should be disabled
      expect(screen.getByTestId('stage-disabled-implement')).toBeInTheDocument()
      expect(screen.queryByTestId('stage-disabled-triage')).not.toBeInTheDocument()
      expect(screen.queryByTestId('stage-disabled-plan')).not.toBeInTheDocument()
      expect(screen.queryByTestId('stage-disabled-review')).not.toBeInTheDocument()

      // Opacity check
      expect(screen.getByTestId('stage-section-implement').style.opacity).toBe('0.5')
      expect(screen.getByTestId('stage-section-triage').style.opacity).toBe('1')
    })
  })
})

describe('toStreamIssue status mapping', () => {
  it('maps active status to overallStatus active', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.overallStatus).toBe('active')
  })

  it('maps queued status to overallStatus queued', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'queued' }, 'plan', [])
    expect(result.overallStatus).toBe('queued')
  })

  it('maps hitl status to overallStatus hitl', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'hitl' }, 'plan', [])
    expect(result.overallStatus).toBe('hitl')
  })

  it('maps failed status to overallStatus failed', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'failed' }, 'plan', [])
    expect(result.overallStatus).toBe('failed')
  })

  it('maps error status to overallStatus failed', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'error' }, 'plan', [])
    expect(result.overallStatus).toBe('failed')
  })

  it('maps merged status to overallStatus done', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'merged' }, 'merged', [])
    expect(result.overallStatus).toBe('done')
  })

  it('maps processing status to overallStatus active', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'processing' }, 'plan', [])
    expect(result.overallStatus).toBe('active')
  })

  it('maps unknown status to overallStatus queued', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'something_else' }, 'plan', [])
    expect(result.overallStatus).toBe('queued')
  })

  it('defaults to queued when status is undefined', () => {
    const result = toStreamIssue({ ...basePipeIssue }, 'plan', [])
    expect(result.overallStatus).toBe('queued')
  })
})

describe('toStreamIssue stage building', () => {
  it('sets every non-conditional stage to done for a merged item', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'merged' },
      'merged',
      []
    )
    for (const key of STAGE_KEYS) {
      if (key === 'hitl') continue
      expect(result.stages[key].status).toBe('done')
    }
    expect(result.overallStatus).toBe('done')
  })

  it('sets current stage to active when issue status is active', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'implement', [])
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('active')
    expect(result.stages.review.status).toBe('pending')
    expect(result.stages.merged.status).toBe('pending')
    expect(result.overallStatus).toBe('active')
  })

  it('sets current stage to queued when issue status is queued', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'queued' }, 'implement', [])
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('queued')
    expect(result.stages.review.status).toBe('pending')
    expect(result.stages.merged.status).toBe('pending')
    expect(result.overallStatus).toBe('queued')
  })

  it('sets current stage to failed for failed items', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'failed' },
      'implement',
      []
    )
    expect(result.overallStatus).toBe('failed')
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('failed')
    expect(result.stages.review.status).toBe('pending')
    expect(result.stages.merged.status).toBe('pending')
  })

  it('sets current stage to hitl for hitl items', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'hitl' },
      'review',
      []
    )
    expect(result.overallStatus).toBe('hitl')
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('done')
    expect(result.stages.review.status).toBe('hitl')
    expect(result.stages.merged.status).toBe('pending')
  })

  it('sets prior stages to done', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'review', [])
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('done')
  })

  it('sets later stages to pending', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.stages.implement.status).toBe('pending')
    expect(result.stages.review.status).toBe('pending')
    expect(result.stages.merged.status).toBe('pending')
  })
})

describe('toStreamIssue hitl conditional stage (#10509)', () => {
  // hitl is a conditional escalation branch, not a linear stage every issue
  // passes through — a merged issue that never escalated must render hitl
  // hollow (pending), not blanket-stamped done just because it's behind the
  // current index. Positive evidence (hitl_visited) is required for done.
  it('renders hitl as pending for a merged issue that never visited hitl', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'merged', hitl_visited: false },
      'merged',
      []
    )
    expect(result.stages.hitl.status).toBe('pending')
  })

  it('renders hitl as pending when hitl_visited is absent (old payloads)', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'merged' },
      'merged',
      []
    )
    expect(result.stages.hitl.status).toBe('pending')
  })

  it('renders hitl as done for a merged issue that previously visited hitl', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'merged', hitl_visited: true },
      'merged',
      []
    )
    expect(result.stages.hitl.status).toBe('done')
  })

  it('renders merged as done for a merged issue', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'merged' },
      'merged',
      []
    )
    expect(result.stages.merged.status).toBe('done')
  })

  it('still renders hitl as the current-stage red hitl status for an issue genuinely sitting in hitl', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'hitl' },
      'hitl',
      []
    )
    expect(result.stages.hitl.status).toBe('hitl')
    expect(result.overallStatus).toBe('hitl')
  })
})

describe('toStreamIssue output shape', () => {
  it('returns correct issueNumber and title', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.issueNumber).toBe(42)
    expect(result.title).toBe('Test issue')
  })

  it('returns currentStage matching the stageKey argument', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'implement', [])
    expect(result.currentStage).toBe('implement')
  })

  it('builds a stages object with all STAGE_KEYS', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    for (const key of STAGE_KEYS) {
      expect(result.stages).toHaveProperty(key)
      expect(result.stages[key]).toHaveProperty('status')
      expect(result.stages[key]).toHaveProperty('startTime')
      expect(result.stages[key]).toHaveProperty('endTime')
      expect(result.stages[key]).toHaveProperty('transcript')
    }
  })

  it('matches PR from prs array by issue_number', () => {
    const prs = [{ issue: 42, pr: 100, url: 'https://github.com/pr/100' }]
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'review', prs)
    expect(result.pr).toEqual({ number: 100, url: 'https://github.com/pr/100' })
  })

  it('returns null pr when no matching PR exists', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.pr).toBeNull()
  })

  it('passes through issueUrl from pipeIssue url field', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.issueUrl).toBe('https://github.com/test/42')
  })

  it('returns null issueUrl when url is empty', () => {
    const result = toStreamIssue(
      { issue_number: 1, title: 'X', url: '', status: 'active' },
      'plan',
      []
    )
    expect(result.issueUrl).toBeNull()
  })

  it('returns null issueUrl when url is missing', () => {
    const result = toStreamIssue(
      { issue_number: 1, title: 'X', status: 'active' },
      'plan',
      []
    )
    expect(result.issueUrl).toBeNull()
  })
})

describe('Stage header failed/hitl counts', () => {
  it('shows failed count when stage has failed issues', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], plan: [], review: [],
        implement: [
          { issue_number: 1, title: 'Active issue', status: 'active' },
          { issue_number: 2, title: 'Failed issue', status: 'failed' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-implement')
    expect(section.textContent).toContain('1 failed')
  })

  it('shows hitl count when stage has hitl issues', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], plan: [], implement: [],
        review: [
          { issue_number: 1, title: 'Active issue', status: 'active' },
          { issue_number: 2, title: 'HITL issue', status: 'hitl' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-review')
    expect(section.textContent).toContain('1 hitl')
  })

  it('hides failed and hitl counts when zero', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], implement: [], review: [],
        plan: [
          { issue_number: 1, title: 'Active issue', status: 'active' },
          { issue_number: 2, title: 'Queued issue', status: 'queued' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-plan')
    expect(section.textContent).not.toContain('failed')
    expect(section.textContent).not.toContain('hitl')
  })

  it('excludes failed and hitl from queued count', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], plan: [], review: [],
        implement: [
          { issue_number: 1, title: 'Active', status: 'active' },
          { issue_number: 2, title: 'Failed', status: 'failed' },
          { issue_number: 3, title: 'HITL', status: 'hitl' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-implement')
    expect(section.textContent).toContain('0 queued')
    expect(section.textContent).toContain('1 failed')
    expect(section.textContent).toContain('1 hitl')
  })

  it('shows correct counts with only failed issues (no active/queued)', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], plan: [], review: [],
        implement: [
          { issue_number: 1, title: 'Failed 1', status: 'failed' },
          { issue_number: 2, title: 'Failed 2', status: 'failed' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-implement')
    expect(section.textContent).toContain('0 queued')
    expect(section.textContent).toContain('2 failed')
  })
})

describe('PipelineFlow visualization', () => {
  it('renders "Pipeline Flow" label in the flow indicator', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [{ issue_number: 1, title: 'Test', status: 'queued' }],
        plan: [], implement: [], review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const flow = screen.getByTestId('pipeline-flow')
    expect(flow.textContent).toContain('Pipeline Flow')
  })

  it('renders all pipeline stage labels in the flow', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [{ issue_number: 1, title: 'Test', status: 'queued' }],
        plan: [], implement: [], review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const flow = screen.getByTestId('pipeline-flow')
    expect(flow).toBeInTheDocument()
    expect(flow.textContent).toContain('Triage')
    expect(flow.textContent).toContain('Plan')
    expect(flow.textContent).toContain('Implement')
    expect(flow.textContent).toContain('Review')
    expect(flow.textContent).toContain('Merged')
  })

  it('renders dots for issues at their current stage', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [
          { issue_number: 10, title: 'Plan issue', status: 'queued' },
          { issue_number: 11, title: 'Plan issue 2', status: 'active' },
        ],
        implement: [],
        review: [{ issue_number: 20, title: 'Review issue', status: 'active' }],
      },
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.getByTestId('flow-dot-10')).toBeInTheDocument()
    expect(screen.getByTestId('flow-dot-11')).toBeInTheDocument()
    expect(screen.getByTestId('flow-dot-20')).toBeInTheDocument()
  })

  it('renders pipeline flow even when no issues exist', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: { triage: [], plan: [], implement: [], review: [] },
    }))
    render(<StreamView {...defaultProps} />)
    const flow = screen.getByTestId('pipeline-flow')
    expect(flow).toBeInTheDocument()
    expect(flow.textContent).toContain('Triage')
    expect(flow.textContent).toContain('Plan')
    expect(flow.textContent).toContain('Implement')
    expect(flow.textContent).toContain('Review')
    expect(flow.textContent).toContain('Merged')
  })

  it('shows all stage labels even when some stages have no issues', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [{ issue_number: 5, title: 'Only plan', status: 'queued' }],
        implement: [], review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const flow = screen.getByTestId('pipeline-flow')
    expect(flow.textContent).toContain('Triage')
    expect(flow.textContent).toContain('Plan')
    expect(flow.textContent).toContain('Implement')
    expect(flow.textContent).toContain('Review')
    expect(flow.textContent).toContain('Merged')
  })

  it('applies pulse animation to active issue dots', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [
          { issue_number: 10, title: 'Active', status: 'active' },
          { issue_number: 11, title: 'Queued', status: 'queued' },
        ],
        implement: [], review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const activeDot = screen.getByTestId('flow-dot-10')
    const queuedDot = screen.getByTestId('flow-dot-11')
    expect(activeDot.style.animation).toContain('stream-pulse')
    expect(queuedDot.style.animation).toBe('')
  })

  it('renders the shared terminal fork with hitl and merged as parallel arms', () => {
    // hitl/merged fork off REVIEW via the shared TerminalFork — the same
    // topology Header's review-terminal-fork renders (#9564).
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext())
    render(<StreamView {...defaultProps} />)
    const fork = screen.getByTestId('flow-terminal-fork')
    expect(fork).toBeInTheDocument()
    expect(fork.textContent).toContain('Needs Human')
    expect(fork.textContent).toContain('Merged')
  })

  it('left-aligns the terminal fork arms so the branch arrows form a column', () => {
    // flowFork previously centered each [arrow][label] row (alignItems:
    // 'center'), which left-shifts the wider "Needs Human" row further than
    // the narrower "Merged" row, misaligning the ↗/↘ glyphs (#10226).
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext())
    render(<StreamView {...defaultProps} />)
    const fork = screen.getByTestId('flow-terminal-fork')
    expect(fork.style.alignItems).toBe('flex-start')
  })
})

describe('Merged stage rendering', () => {
  it('renders merged issues from pipeline snapshot in the merged stage section', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], implement: [], review: [],
        merged: [{ issue_number: 10, title: 'Fix bug', url: '', status: 'done' }],
      },
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.getByText('#10')).toBeInTheDocument()
    expect(screen.getByText('Fix bug')).toBeInTheDocument()
  })

  it('renders merged issue as a dot in PipelineFlow', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], implement: [], review: [],
        merged: [{ issue_number: 10, title: 'Fix bug', url: '', status: 'done' }],
      },
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.getByTestId('pipeline-flow')).toBeInTheDocument()
    const dot = screen.getByTestId('flow-dot-10')
    expect(dot).toBeInTheDocument()
    expect(dot.style.animation).toBe('')
  })

  it('does not set issueUrl when url is null for merged cards', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Fix bug', url: null, status: 'done' },
      'merged',
      []
    )
    expect(result.issueUrl).toBeNull()
  })
})

describe('Merged stage count display', () => {
  it('shows merged item count instead of worker metrics', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], implement: [], review: [],
        merged: [{ issue_number: 10, title: 'Fix bug', url: '', status: 'done' }],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    expect(section.textContent).toContain('1 merged')
    expect(section.textContent).not.toContain('active')
    expect(section.textContent).not.toContain('queued')
    expect(section.textContent).not.toContain('workers')
  })

  it('shows correct count with multiple merged items', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], implement: [], review: [],
        merged: [
          { issue_number: 10, title: 'Fix bug', url: '', status: 'done' },
          { issue_number: 11, title: 'Add feature', url: '', status: 'done' },
          { issue_number: 12, title: 'Refactor', url: '', status: 'done' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    expect(section.textContent).toContain('3 merged')
  })

  it('shows "0 merged" when no merged items exist', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext())
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    expect(section.textContent).toContain('0 merged')
  })

  it('does not affect worker metrics display on non-merged stages', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], review: [],
        implement: [
          { issue_number: 1, title: 'Active issue', status: 'active' },
          { issue_number: 2, title: 'Queued issue', status: 'queued' },
        ],
      },
      pipelineStats: {
        stages: { implement: { queued: 1, active: 1, completed_session: 0, worker_count: 0 } },
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-implement')
    expect(section.textContent).toContain('1 queued')
    expect(section.textContent).toContain('worker')
  })

  it('counts items from pipelineIssues.merged', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], implement: [], review: [],
        merged: [
          { issue_number: 5, title: 'Pipeline merged issue', status: 'done' },
          { issue_number: 6, title: 'Another merged issue', status: 'done' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    expect(section.textContent).toContain('2 merged')
  })
})

describe('PipelineFlow failed and hitl dots', () => {
  it('renders failed dots with red background and no animation', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 1, title: 'Failed issue', status: 'failed' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const dot = screen.getByTestId('flow-dot-1')
    expect(dot).toBeInTheDocument()
    expect(dot.style.background).toBe('var(--red)')
    expect(dot.style.animation).toBe('')
  })

  it('renders hitl dots with red background and no animation', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 2, title: 'HITL issue', status: 'hitl' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const dot = screen.getByTestId('flow-dot-2')
    expect(dot).toBeInTheDocument()
    expect(dot.style.background).toBe('var(--red)')
    expect(dot.style.animation).toBe('')
  })

  it('renders queued dots with subtle stage color', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 3, title: 'Queued issue', status: 'queued' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const dot = screen.getByTestId('flow-dot-3')
    expect(dot.style.background).toBe('var(--accent-subtle)')
    expect(dot.style.animation).toBe('')
  })

  it('renders mixed status dots with correct colors in the same stage', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 10, title: 'Active', status: 'active' },
          { issue_number: 11, title: 'Failed', status: 'failed' },
          { issue_number: 12, title: 'HITL', status: 'hitl' },
          { issue_number: 13, title: 'Queued', status: 'queued' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    // Active: stage color (accent) + pulse animation
    const activeDot = screen.getByTestId('flow-dot-10')
    expect(activeDot.style.background).toBe('var(--accent)')
    expect(activeDot.style.animation).toContain('stream-pulse')
    // Failed: red, no animation
    const failedDot = screen.getByTestId('flow-dot-11')
    expect(failedDot.style.background).toBe('var(--red)')
    expect(failedDot.style.animation).toBe('')
    // HITL: red, no animation (shares Failed's hue in the glyph-less flow view)
    const hitlDot = screen.getByTestId('flow-dot-12')
    expect(hitlDot.style.background).toBe('var(--red)')
    expect(hitlDot.style.animation).toBe('')
    // Queued: subtle stage color (accent), no animation
    const queuedDot = screen.getByTestId('flow-dot-13')
    expect(queuedDot.style.background).toBe('var(--accent-subtle)')
    expect(queuedDot.style.animation).toBe('')
  })
})

describe('PipelineFlow summary counts', () => {
  it('shows summary counts when merged and failed issues exist', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 1, title: 'Failed', status: 'failed' },
        ],
        review: [],
        merged: [
          { issue_number: 10, title: 'Fix bug', url: '', status: 'done' },
          { issue_number: 11, title: 'Add feature', url: '', status: 'done' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const summary = screen.getByTestId('flow-summary')
    expect(summary).toBeInTheDocument()
    expect(summary.textContent).toContain('2 merged')
    expect(summary.textContent).toContain('1 failed')
  })

  it('shows only merged count when no failed issues', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [],
        review: [],
        merged: [
          { issue_number: 10, title: 'Fix bug', url: '', status: 'done' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const summary = screen.getByTestId('flow-summary')
    expect(summary.textContent).toContain('1 merged')
    expect(summary.textContent).not.toContain('failed')
  })

  it('shows only failed count when no merged issues', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 1, title: 'Failed', status: 'failed' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const summary = screen.getByTestId('flow-summary')
    expect(summary.textContent).toContain('1 failed')
    expect(summary.textContent).not.toContain('merged')
  })

  it('hides summary when both counts are zero', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [{ issue_number: 1, title: 'Queued', status: 'queued' }],
        implement: [],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.queryByTestId('flow-summary')).not.toBeInTheDocument()
  })
})

describe('findWorkerTranscript', () => {
  const workers = {
    'triage-42': { transcript: ['triaging issue 42'] },
    'plan-42': { transcript: ['planning issue 42'] },
    '42': { transcript: ['implementing issue 42'] },
    'review-100': { transcript: ['reviewing PR 100'] },
  }
  const prs = [{ issue: 42, pr: 100, url: 'https://github.com/pr/100' }]

  it('matches triage worker by triage-{issueNumber} key', () => {
    const result = findWorkerTranscript(workers, prs, 'triage', 42)
    expect(result).toEqual(['triaging issue 42'])
  })

  it('finds the repo-qualified transcript under __all__ (same issue, two repos)', () => {
    const repoWorkers = {
      'owner-a#42': { transcript: ['a-line'] },
      'owner-b#42': { transcript: ['b-line'] },
    }
    expect(findWorkerTranscript(repoWorkers, [], 'implement', 42, 'owner-a')).toEqual(['a-line'])
    expect(findWorkerTranscript(repoWorkers, [], 'implement', 42, 'owner-b')).toEqual(['b-line'])
  })

  it('matches the review transcript by (issue, repo), not the first same-issue PR', () => {
    const repoWorkers = { 'review-owner-b#7': { transcript: ['rev-b'] } }
    const repoPrs = [
      { pr: 7, issue: 42, repo: 'owner-a' },
      { pr: 7, issue: 42, repo: 'owner-b' },
    ]
    expect(findWorkerTranscript(repoWorkers, repoPrs, 'review', 42, 'owner-b')).toEqual(['rev-b'])
  })

  it('matches plan worker by plan-{issueNumber} key', () => {
    const result = findWorkerTranscript(workers, prs, 'plan', 42)
    expect(result).toEqual(['planning issue 42'])
  })

  it('matches implement worker by bare issue number key', () => {
    const result = findWorkerTranscript(workers, prs, 'implement', 42)
    expect(result).toEqual(['implementing issue 42'])
  })

  it('matches review worker via PR lookup to review-{prNumber} key', () => {
    const result = findWorkerTranscript(workers, prs, 'review', 42)
    expect(result).toEqual(['reviewing PR 100'])
  })

  it('returns empty array when no matching worker exists', () => {
    const result = findWorkerTranscript(workers, prs, 'implement', 999)
    expect(result).toEqual([])
  })

  it('returns empty array for merged stage', () => {
    const result = findWorkerTranscript(workers, prs, 'merged', 42)
    expect(result).toEqual([])
  })

  it('returns empty array when worker exists but has no transcript', () => {
    const workersNoTranscript = { '42': { status: 'running' } }
    const result = findWorkerTranscript(workersNoTranscript, [], 'implement', 42)
    expect(result).toEqual([])
  })

  it('returns empty array when workers is null', () => {
    const result = findWorkerTranscript(null, prs, 'triage', 42)
    expect(result).toEqual([])
  })

  it('returns empty array for review when no PR exists for issue', () => {
    const result = findWorkerTranscript(workers, [], 'review', 42)
    expect(result).toEqual([])
  })
})

describe('StreamView transcript integration', () => {
  it('passes transcript to StreamCard for active issue with matching worker', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], review: [],
        implement: [{ issue_number: 42, title: 'Test issue', status: 'active' }],
      },
      workers: {
        '42': { status: 'running', worker: 1, role: 'implementer', title: 'Test issue', branch: '', transcript: ['line 1', 'line 2', 'line 3'], pr: null },
      },
    }))
    render(<StreamView {...defaultProps} />)
    // Active card should be expanded by default and show transcript preview
    expect(screen.getByTestId('transcript-preview')).toBeInTheDocument()
    expect(screen.getByText('line 1')).toBeInTheDocument()
  })

  it('does not show transcript for queued issues even with worker data', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], review: [],
        implement: [{ issue_number: 42, title: 'Test issue', status: 'queued' }],
      },
      workers: {
        '42': { status: 'queued', worker: 1, role: 'implementer', title: 'Test issue', branch: '', transcript: ['line 1'], pr: null },
      },
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })
})

describe('StageSection reconciled queued count (#9793)', () => {
  it('derives the queued count from the rendered rows, showing snapshot lag as syncing', () => {
    // Orchestrator says 3 queued, snapshot has 1 row: header must match the
    // list (1) and surface the lag honestly instead of a phantom count.
    const ctx = defaultHydraFlowContext({
      pipelineIssues: {
        plan: [{ issue_number: 1, title: 'Q1', status: 'queued' }],
      },
    })
    ctx.stageStatus = {
      ...ctx.stageStatus,
      plan: { ...(ctx.stageStatus.plan || {}), enabled: true, queuedCount: 3, workerCount: 0 },
    }
    mockUseHydraFlow.mockReturnValue(ctx)
    render(<StreamView {...defaultProps} />)

    const queued = screen.getByTestId('stage-queued-plan')
    expect(queued.textContent).toContain('1 queued')
    expect(queued.textContent).toContain('(+2 syncing)')
  })

  it('shows no syncing suffix when header and list agree', () => {
    const ctx = defaultHydraFlowContext({
      pipelineIssues: {
        plan: [{ issue_number: 2, title: 'Q2', status: 'queued' }],
      },
    })
    ctx.stageStatus = {
      ...ctx.stageStatus,
      plan: { ...(ctx.stageStatus.plan || {}), enabled: true, queuedCount: 1, workerCount: 0 },
    }
    mockUseHydraFlow.mockReturnValue(ctx)
    render(<StreamView {...defaultProps} />)

    const queued = screen.getByTestId('stage-queued-plan')
    expect(queued.textContent).toContain('1 queued')
    expect(queued.textContent).not.toContain('syncing')
  })
})

describe('PipelineFlow dot cap (#9863)', () => {
  it('caps a large backlog at 10 dots with a +N overflow badge', () => {
    const many = Array.from({ length: 67 }, (_, i) => ({
      issue_number: 1000 + i,
      title: `Q${i}`,
      status: 'queued',
    }))
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: { plan: many },
    }))
    render(<StreamView {...defaultProps} />)

    const overflow = screen.getByTestId('flow-overflow-plan')
    expect(overflow.textContent).toBe('+57')
    // Only the capped dots render (first 10 issue numbers).
    expect(screen.getByTestId('flow-dot-1009')).toBeTruthy()
    expect(screen.queryByTestId('flow-dot-1010')).toBeNull()
  })

  it('renders no overflow badge at or under the cap', () => {
    const few = Array.from({ length: 10 }, (_, i) => ({
      issue_number: 2000 + i,
      title: `Q${i}`,
      status: 'queued',
    }))
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: { plan: few },
    }))
    render(<StreamView {...defaultProps} />)

    expect(screen.queryByTestId('flow-overflow-plan')).toBeNull()
    expect(screen.getByTestId('flow-dot-2009')).toBeTruthy()
  })
})

describe('PipelineFlow region + total count badges (#10488)', () => {
  it('shows the per-region issue count as a bare "N" with no "· N PR" suffix', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        plan: [
          { issue_number: 1, title: 'P1', status: 'queued' },
          { issue_number: 2, title: 'P2', status: 'queued' },
        ],
        implement: [
          { issue_number: 3, title: 'I1', status: 'queued' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)

    expect(screen.getByTestId('flow-count-plan').textContent).toBe('2')
    expect(screen.getByTestId('flow-count-implement').textContent).toBe('1')
    // #10593: the PR count suffix is gone entirely — no badge mentions PR.
    expect(screen.getByTestId('flow-count-plan').textContent).not.toContain('PR')
    expect(screen.getByTestId('flow-count-implement').textContent).not.toContain('PR')
  })

  it('drops the PR count for REVIEW even when issues carry a PR, keeping only the issue count', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [
          { issue_number: 4, title: 'T1', status: 'queued' },
          { issue_number: 5, title: 'T2', status: 'queued' },
        ],
        review: [
          { issue_number: 1, title: 'R1', status: 'active' },
          { issue_number: 2, title: 'R2', status: 'active' },
          { issue_number: 3, title: 'R3', status: 'queued' },
        ],
      },
      prs: [
        { issue: 1, pr: 101, url: 'https://github.com/pr/101' },
        { issue: 2, pr: 102, url: 'https://github.com/pr/102' },
      ],
    }))
    render(<StreamView {...defaultProps} />)

    // REVIEW has 2 PRs, but the badge no longer surfaces that — issue count only.
    expect(screen.getByTestId('flow-count-review').textContent).toBe('3')
    expect(screen.getByTestId('flow-count-review').textContent).not.toContain('PR')
    expect(screen.getByTestId('flow-count-triage').textContent).toBe('2')
    // The hover tooltip must not mention PRs either (acceptance criterion).
    expect(screen.getByTestId('flow-count-review').getAttribute('title')).not.toContain('PR')
  })

  it('renders flow-count badges for the terminal-fork stages hitl and merged', () => {
    // hitl/merged render via the shared TerminalFork -> renderFlowStage path,
    // not the plain postTriageGroups.map path — assert both explicitly so a
    // regression that special-cases the fork doesn't silently drop the badge.
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        hitl: [{ issue_number: 77, title: 'Escalated issue', status: 'hitl' }],
        merged: [{ issue_number: 10, title: 'Fix bug', url: '', status: 'done' }],
      },
    }))
    render(<StreamView {...defaultProps} />)

    expect(screen.getByTestId('flow-count-hitl')).toBeTruthy()
    expect(screen.getByTestId('flow-count-hitl').textContent).toBe('1')
    expect(screen.getByTestId('flow-count-merged')).toBeTruthy()
    expect(screen.getByTestId('flow-count-merged').textContent).toBe('1')
  })

  it('shows the full issue count in the region badge even when dots are capped at 10', () => {
    // #9863 caps rendered dots at 10 with a +N overflow badge — the count
    // badge must still report the FULL group.issues.length (via countRegion),
    // not the capped dot count.
    const many = Array.from({ length: 11 }, (_, i) => ({
      issue_number: 3000 + i,
      title: `Q${i}`,
      status: 'queued',
    }))
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: { plan: many },
    }))
    render(<StreamView {...defaultProps} />)

    expect(screen.getByTestId('flow-count-plan').textContent).toBe('11')
    expect(screen.getByTestId('flow-overflow-plan').textContent).toBe('+1')
    expect(screen.getByTestId('flow-dot-3009')).toBeTruthy()
    expect(screen.queryByTestId('flow-dot-3010')).toBeNull()
  })

  it('shows the pipeline-wide total as "N issues" with no "· N PRs" suffix', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [
          { issue_number: 1, title: 'T1', status: 'queued' },
          { issue_number: 2, title: 'T2', status: 'queued' },
        ],
        review: [
          { issue_number: 3, title: 'R1', status: 'active' },
        ],
      },
      prs: [
        { issue: 3, pr: 300, url: 'https://github.com/pr/300' },
      ],
    }))
    render(<StreamView {...defaultProps} />)

    expect(screen.getByTestId('flow-total').textContent).toBe('3 issues')
    expect(screen.getByTestId('flow-total').textContent).not.toContain('PR')
    expect(screen.getByTestId('flow-total').getAttribute('title')).not.toContain('PR')
  })

  it('updates flow-count-plan after the context snapshot changes and the component re-renders', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        plan: [{ issue_number: 1, title: 'P1', status: 'queued' }],
      },
    }))
    const { rerender } = render(<StreamView {...defaultProps} />)
    expect(screen.getByTestId('flow-count-plan').textContent).toBe('1')

    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        plan: [
          { issue_number: 1, title: 'P1', status: 'queued' },
          { issue_number: 2, title: 'P2', status: 'queued' },
          { issue_number: 3, title: 'P3', status: 'queued' },
        ],
      },
    }))
    rerender(<StreamView {...defaultProps} />)
    expect(screen.getByTestId('flow-count-plan').textContent).toBe('3')
  })
})

describe('work-queue strategy visualisation (#10067)', () => {
  it('shows the active strategy badge from config', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      config: { queue_strategy: 'weighted_mix' },
    }))
    render(<StreamView {...defaultProps} />)

    const badge = screen.getByTestId('queue-strategy-badge')
    expect(badge.textContent).toContain('weighted')
  })

  it('shows fifo when the escape hatch is active', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      config: { queue_strategy: 'fifo' },
    }))
    render(<StreamView {...defaultProps} />)

    expect(screen.getByTestId('queue-strategy-badge').textContent).toContain('fifo')
  })

  it('renders no strategy badge when config lacks the field (old backend)', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({ config: {} }))
    render(<StreamView {...defaultProps} />)

    expect(screen.queryByTestId('queue-strategy-badge')).toBeNull()
  })

  it('orders queued cards by dispatch_rank, not arrival order', () => {
    // Arrival order is 91, 92, 93; the backend says dispatch order is 93, 91, 92
    // (e.g. a P0 that arrived last). The board must reflect dispatch order so the
    // top card is what the factory works next.
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        implement: [
          { issue_number: 91, title: 'first in', status: 'queued', priority: 'P2', dispatch_rank: 1 },
          { issue_number: 92, title: 'second in', status: 'queued', priority: 'none', dispatch_rank: 2 },
          { issue_number: 93, title: 'last in, picked first', status: 'queued', priority: 'P0', dispatch_rank: 0 },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)

    const cards = screen.getAllByTestId(/^stream-card-9[123]$/)
    const order = cards.map(c => Number(c.getAttribute('data-testid').replace('stream-card-', '')))
    expect(order).toEqual([93, 91, 92])
  })

  it('keeps active cards ahead of queued ones regardless of rank', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        implement: [
          { issue_number: 81, title: 'queued, rank 0', status: 'queued', priority: 'P0', dispatch_rank: 0 },
          { issue_number: 82, title: 'active', status: 'active', priority: 'P2' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)

    const cards = screen.getAllByTestId(/^stream-card-8[12]$/)
    const order = cards.map(c => Number(c.getAttribute('data-testid').replace('stream-card-', '')))
    expect(order).toEqual([82, 81])
  })
})

describe('Epics moved off the pipeline view (#10306)', () => {
  // Epics used to render as an EpicOverviewPanel on the stream/pipeline view.
  // They now live on the Outcomes tab as outcome cards (EpicOutcomeCards), so
  // StreamView must NOT mount any epic overview panel or epic badge, even when
  // the context carries epics.
  const baseEpic = {
    epic_number: 10239,
    title: 'Epic Alpha',
    status: 'active',
    percent_complete: 0,
    completed: 0,
    failed: 0,
    total_children: 2,
    in_progress: 2,
    active_children: 1,
    queued_children: 0,
  }

  it('does not render the epic overview panel or epic badges', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      epics: [baseEpic],
    }))
    render(<StreamView {...defaultProps} />)

    expect(screen.queryByTestId(`epic-badge-${baseEpic.epic_number}`)).not.toBeInTheDocument()
    // The panel's "Epics" heading must not appear on the pipeline view.
    expect(screen.queryByText('Epics')).not.toBeInTheDocument()
  })
})

// TranscriptRow (#10556 Task 4) is the shared, presentational transcript-line
// row renderer extracted from StreamView so the operator console's
// TranscriptStream reuses one row implementation instead of forking its own.
// Additive export — StreamView's own render path and tests are unchanged.
describe('TranscriptRow (shared transcript-line renderer)', () => {
  it('renders a kind-tagged row with a timestamp and its text', () => {
    render(<TranscriptRow row={{ ts: '2026-07-26T12:00:02Z', kind: 'edit', text: 'writing config.py' }} />)
    const el = screen.getByTestId('transcript-row')
    expect(el).toHaveAttribute('data-kind', 'edit')
    expect(screen.getByTestId('transcript-ts')).toHaveTextContent('12:00:02')
    expect(screen.getByText('writing config.py')).toBeInTheDocument()
  })

  it('falls back to the agent kind for an unknown kind', () => {
    render(<TranscriptRow row={{ ts: '2026-07-26T12:00:02Z', kind: 'weird', text: 'x' }} />)
    expect(screen.getByTestId('transcript-row')).toHaveAttribute('data-kind', 'weird')
  })
})
