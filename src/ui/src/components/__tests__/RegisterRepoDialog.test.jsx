import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { RegisterRepoDialog } = await import('../RegisterRepoDialog')

function defaultContext(overrides = {}) {
  return {
    addRepoByPath: vi.fn().mockResolvedValue({ ok: true }),
    startRuntime: vi.fn().mockResolvedValue({ ok: true }),
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultContext())
})

describe('RegisterRepoDialog', () => {
  it('does not render when isOpen is false', () => {
    render(<RegisterRepoDialog isOpen={false} onClose={vi.fn()} />)
    expect(screen.queryByTestId('register-repo-dialog')).toBeNull()
  })

  it('renders when isOpen is true', () => {
    render(<RegisterRepoDialog isOpen={true} onClose={vi.fn()} />)
    expect(screen.getByTestId('register-repo-dialog')).toBeInTheDocument()
    expect(screen.getByText('Register Repository')).toBeInTheDocument()
  })

  it('has input field with correct placeholder', () => {
    render(<RegisterRepoDialog isOpen={true} onClose={vi.fn()} />)
    const input = screen.getByTestId('register-repo-input')
    expect(input).toHaveAttribute('placeholder', 'owner/repo or /path/to/repo')
  })

  it('submit button is disabled when input is empty', () => {
    render(<RegisterRepoDialog isOpen={true} onClose={vi.fn()} />)
    expect(screen.getByTestId('register-repo-submit')).toBeDisabled()
  })

  it('submit button is enabled when input has content', () => {
    render(<RegisterRepoDialog isOpen={true} onClose={vi.fn()} />)
    fireEvent.change(screen.getByTestId('register-repo-input'), {
      target: { value: 'org/repo' },
    })
    expect(screen.getByTestId('register-repo-submit')).not.toBeDisabled()
  })

  it('calls startRuntime for slug-format input', async () => {
    const startRuntime = vi.fn().mockResolvedValue({ ok: true })
    const onClose = vi.fn()
    mockUseHydraFlow.mockReturnValue(defaultContext({ startRuntime }))

    render(<RegisterRepoDialog isOpen={true} onClose={onClose} />)
    fireEvent.change(screen.getByTestId('register-repo-input'), {
      target: { value: 'org/repo' },
    })
    fireEvent.click(screen.getByTestId('register-repo-submit'))

    await waitFor(() => {
      expect(startRuntime).toHaveBeenCalledWith('org/repo')
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('calls addRepoByPath for filesystem path input', async () => {
    const addRepoByPath = vi.fn().mockResolvedValue({ ok: true })
    const onClose = vi.fn()
    mockUseHydraFlow.mockReturnValue(defaultContext({ addRepoByPath }))

    render(<RegisterRepoDialog isOpen={true} onClose={onClose} />)
    fireEvent.change(screen.getByTestId('register-repo-input'), {
      target: { value: '/home/user/my-repo' },
    })
    fireEvent.click(screen.getByTestId('register-repo-submit'))

    await waitFor(() => {
      expect(addRepoByPath).toHaveBeenCalledWith('/home/user/my-repo')
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('shows error message on failure', async () => {
    const startRuntime = vi.fn().mockResolvedValue({ ok: false, error: 'Repo not found' })
    mockUseHydraFlow.mockReturnValue(defaultContext({ startRuntime }))

    render(<RegisterRepoDialog isOpen={true} onClose={vi.fn()} />)
    fireEvent.change(screen.getByTestId('register-repo-input'), {
      target: { value: 'org/repo' },
    })
    fireEvent.click(screen.getByTestId('register-repo-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('register-repo-error')).toHaveTextContent('Repo not found')
    })
  })

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen={true} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('register-repo-close'))
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onClose when overlay is clicked', () => {
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen={true} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('register-repo-overlay'))
    expect(onClose).toHaveBeenCalled()
  })

  it('does not close when dialog content is clicked', () => {
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen={true} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('register-repo-dialog'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('resets input when reopened', () => {
    const { rerender } = render(
      <RegisterRepoDialog isOpen={true} onClose={vi.fn()} />
    )
    fireEvent.change(screen.getByTestId('register-repo-input'), {
      target: { value: 'org/repo' },
    })
    expect(screen.getByTestId('register-repo-input')).toHaveValue('org/repo')

    rerender(<RegisterRepoDialog isOpen={false} onClose={vi.fn()} />)
    rerender(<RegisterRepoDialog isOpen={true} onClose={vi.fn()} />)
    expect(screen.getByTestId('register-repo-input')).toHaveValue('')
  })

  it('shows error on addRepoByPath failure for path input', async () => {
    const addRepoByPath = vi.fn().mockResolvedValue({ ok: false, error: 'Directory not found' })
    mockUseHydraFlow.mockReturnValue(defaultContext({ addRepoByPath }))

    render(<RegisterRepoDialog isOpen={true} onClose={vi.fn()} />)
    fireEvent.change(screen.getByTestId('register-repo-input'), {
      target: { value: '/bad/path' },
    })
    fireEvent.click(screen.getByTestId('register-repo-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('register-repo-error')).toHaveTextContent('Directory not found')
    })
  })
})
