import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { BootstrapWizard } = await import('../BootstrapWizard')

function makeContext(overrides = {}) {
  return {
    createOnboardingDraft: vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool', tech_stack: ['python'], safety_guards: [] },
        events: [{ level: 'info', message: 'draft created' }],
      },
    }),
    chatOnboardingDraft: vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: {
          name: 'finance-tool',
          description: 'Finance automation',
          owner: 'T-rav',
          visibility: 'public',
          tech_stack: ['python', 'FastAPI', 'React'],
          safety_guards: ['branch-protection'],
          coverage_floor: 92,
          label_prefix: 'hydraflow',
          main_branch: 'main',
          staging_branch: 'staging',
        },
        chat_messages: [
          { role: 'user', content: 'Build finance-tool with FastAPI and React' },
          { role: 'assistant', content: 'I updated the project fields.' },
        ],
        events: [{ level: 'info', message: 'design chat updated fields' }],
      },
      reply: 'I updated the project fields.',
      field_updates: { name: 'finance-tool' },
    }),
    draftOnboardingSpec: vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool' },
        spec_draft: '# finance-tool\n\n## 10-file Invariant Kernel\n\n## V1 IN',
        events: [{ level: 'info', message: 'wizard spec drafted' }],
      },
      spec_draft: '# finance-tool\n\n## 10-file Invariant Kernel\n\n## V1 IN',
    }),
    saveOnboardingSpecDraft: vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool' },
        spec_draft: '# finance-tool\n\n## Edited',
        events: [{ level: 'info', message: 'wizard spec edits saved' }],
      },
      spec_draft: '# finance-tool\n\n## Edited',
    }),
    draftOnboardingPlan: vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool' },
        plan_draft: ['Create invariant kernel', 'Build UI scaffold'],
        events: [{ level: 'info', message: 'wizard plan drafted' }],
      },
      plan_draft: ['Create invariant kernel', 'Build UI scaffold'],
    }),
    materializeOnboardingDraft: vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool' },
        events: [{ level: 'info', message: 'materialized invariant kernel' }],
      },
      materialized: { path: '/tmp/finance-tool' },
    }),
    selectRepo: vi.fn(),
    ...overrides,
  }
}

describe('BootstrapWizard', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(makeContext())
  })

  it('does not render when closed', () => {
    const { container } = render(<BootstrapWizard isOpen={false} onClose={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('creates a draft before entering the spec step', async () => {
    const createOnboardingDraft = vi.fn().mockResolvedValue({
      ok: true,
      draft: { id: 'draft-2', spec: { name: 'new-project' }, events: [] },
    })
    const draftOnboardingSpec = vi.fn().mockResolvedValue({
      ok: true,
      draft: { id: 'draft-2', spec: { name: 'new-project' }, spec_draft: '# new-project' },
      spec_draft: '# new-project',
    })
    mockUseHydraFlow.mockReturnValue(makeContext({ createOnboardingDraft, draftOnboardingSpec }))

    render(<BootstrapWizard isOpen onClose={() => {}} />)
    fireEvent.click(screen.getByText('Next'))

    await waitFor(() => expect(createOnboardingDraft).toHaveBeenCalled())
    await waitFor(() => expect(draftOnboardingSpec).toHaveBeenCalledWith('draft-2'))
    expect(screen.getByDisplayValue('# new-project')).toBeInTheDocument()
  })

  it('uses design chat to auto-fill fields while keeping them editable', async () => {
    const chatOnboardingDraft = vi
      .fn()
      .mockImplementation(async (_draftId, _message, options) => {
        options?.onReplyDelta?.('I updated ')
        options?.onReplyDelta?.('the project fields.')
        return {
          ok: true,
          draft: {
            id: 'draft-1',
            spec: {
              name: 'finance-tool',
              description: 'Finance automation',
              owner: 'T-rav',
              visibility: 'public',
              tech_stack: ['python', 'FastAPI', 'React'],
              safety_guards: ['branch-protection'],
              coverage_floor: 92,
              label_prefix: 'hydraflow',
              main_branch: 'main',
              staging_branch: 'staging',
            },
            chat_messages: [
              { role: 'user', content: 'Build finance-tool with FastAPI and React' },
              { role: 'assistant', content: 'I updated the project fields.' },
            ],
            events: [{ level: 'info', message: 'design chat updated fields' }],
          },
          reply: 'I updated the project fields.',
          field_updates: { name: 'finance-tool' },
        }
      })
    mockUseHydraFlow.mockReturnValue(makeContext({ chatOnboardingDraft }))

    render(<BootstrapWizard isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('Design chat message'), {
      target: { value: 'Build finance-tool as a public FastAPI React app with 92% coverage' },
    })
    fireEvent.click(screen.getByText('Send'))

    await waitFor(() => expect(chatOnboardingDraft).toHaveBeenCalledWith(
      'draft-1',
      'Build finance-tool as a public FastAPI React app with 92% coverage',
      expect.objectContaining({ onReplyDelta: expect.any(Function) })
    ))
    expect(screen.getByTestId('design-chat-log')).toHaveTextContent('I updated the project fields.')
    expect(screen.getByDisplayValue('finance-tool')).toBeInTheDocument()
    expect(screen.getByLabelText('Visibility')).toHaveValue('public')
    fireEvent.change(screen.getByDisplayValue('finance-tool'), { target: { value: 'ledger-lab' } })
    expect(screen.getByDisplayValue('ledger-lab')).toBeInTheDocument()
  })

  it('materializes the active draft and selects the generated repo', async () => {
    const materializeOnboardingDraft = vi.fn().mockResolvedValue({
      ok: true,
      draft: { id: 'draft-1', spec: { name: 'finance-tool' }, events: [] },
    })
    const selectRepo = vi.fn()
    const onClose = vi.fn()
    mockUseHydraFlow.mockReturnValue(makeContext({ materializeOnboardingDraft, selectRepo }))

    render(<BootstrapWizard isOpen onClose={onClose} />)
    fireEvent.click(screen.getByText('Next'))
    await screen.findByDisplayValue(/10-file Invariant Kernel/)
    fireEvent.click(screen.getByText('Next'))
    await screen.findByText('Build UI scaffold')
    fireEvent.click(screen.getByText('Next'))
    fireEvent.click(screen.getByTestId('materialize-project'))

    await waitFor(() => expect(materializeOnboardingDraft).toHaveBeenCalledWith('draft-1', { output_dir: null }))
    expect(selectRepo).toHaveBeenCalledWith('finance-tool')
    expect(onClose).toHaveBeenCalled()
  })

  it('persists manual spec edits before generating Plan 01', async () => {
    const saveOnboardingSpecDraft = vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool' },
        spec_draft: '# finance-tool\n\n## Edited invariant kernel',
        events: [{ level: 'info', message: 'wizard spec edits saved' }],
      },
      spec_draft: '# finance-tool\n\n## Edited invariant kernel',
    })
    const draftOnboardingPlan = vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool' },
        plan_draft: ['Create invariant kernel'],
        events: [{ level: 'info', message: 'wizard plan drafted' }],
      },
      plan_draft: ['Create invariant kernel'],
    })
    mockUseHydraFlow.mockReturnValue(makeContext({ saveOnboardingSpecDraft, draftOnboardingPlan }))

    render(<BootstrapWizard isOpen onClose={() => {}} />)
    fireEvent.click(screen.getByText('Next'))
    const specEditor = await screen.findByLabelText('Generated spec draft')
    fireEvent.change(specEditor, {
      target: { value: '# finance-tool\n\n## Edited invariant kernel' },
    })
    fireEvent.click(screen.getByText('Next'))

    await waitFor(() => expect(saveOnboardingSpecDraft).toHaveBeenCalledWith(
      'draft-1',
      '# finance-tool\n\n## Edited invariant kernel'
    ))
    await waitFor(() => expect(draftOnboardingPlan).toHaveBeenCalledWith('draft-1'))
  })

  it('keeps the wizard open and expands activity on materialize failure', async () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      materializeOnboardingDraft: vi.fn().mockResolvedValue({
        ok: false,
        error: 'Draft could not be materialized',
        draft: {
          id: 'draft-1',
          spec: { name: 'new-project' },
          events: [{ level: 'error', message: 'target directory already exists' }],
        },
      }),
    }))

    render(<BootstrapWizard isOpen onClose={() => {}} />)
    fireEvent.click(screen.getByText('Next'))
    await screen.findByDisplayValue(/10-file Invariant Kernel/)
    fireEvent.click(screen.getByText('Next'))
    await screen.findByText('Build UI scaffold')
    fireEvent.click(screen.getByText('Next'))
    fireEvent.click(screen.getByTestId('materialize-project'))

    await screen.findByText('Draft could not be materialized')
    expect(screen.getByTestId('wizard-activity-log')).toHaveTextContent('target directory already exists')
  })
})
