import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
  normalizeRepoSlug: (v) => String(v || '').trim().replace(/[\\/]+/g, '-'),
}))

const { RepoSelector } = await import('../RepoSelector')

function defaultContext(overrides = {}) {
  return {
    supervisedRepos: [],
    runtimes: [],
    selectedRepoSlug: null,
    selectRepo: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultContext())
})

describe('RepoSelector', () => {
  it('renders with "All repos" label when no repo selected', () => {
    render(<RepoSelector />)
    expect(screen.getByTestId('repo-selector-trigger')).toHaveTextContent('All repos')
  })

  it('renders selected repo name when a repo is selected', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      supervisedRepos: [{ slug: 'org/my-repo', path: '/tmp/repo' }],
      selectedRepoSlug: 'org-my-repo',
    }))
    render(<RepoSelector />)
    expect(screen.getByTestId('repo-selector-trigger')).toHaveTextContent('org/my-repo')
  })

  it('opens dropdown on click', () => {
    render(<RepoSelector />)
    expect(screen.queryByTestId('repo-selector-dropdown')).toBeNull()
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-selector-dropdown')).toBeInTheDocument()
  })

  it('shows "All repos" option in dropdown', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      supervisedRepos: [{ slug: 'org/repo', path: '/tmp/repo' }],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-option-all')).toBeInTheDocument()
  })

  it('shows repo entries with status dots', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      supervisedRepos: [
        { slug: 'org/repo-a', path: '/a' },
        { slug: 'org/repo-b', path: '/b' },
      ],
      runtimes: [
        { slug: 'org/repo-a', running: true },
        { slug: 'org/repo-b', running: false },
      ],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-option-org-repo-a')).toBeInTheDocument()
    expect(screen.getByTestId('repo-option-org-repo-b')).toBeInTheDocument()
  })

  it('calls selectRepo when an option is clicked', () => {
    const selectRepo = vi.fn()
    mockUseHydraFlow.mockReturnValue(defaultContext({
      supervisedRepos: [{ slug: 'org/repo', path: '/tmp/repo' }],
      selectRepo,
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    fireEvent.click(screen.getByTestId('repo-option-org-repo'))
    expect(selectRepo).toHaveBeenCalledWith('org/repo')
  })

  it('calls selectRepo(null) when "All repos" is clicked', () => {
    const selectRepo = vi.fn()
    mockUseHydraFlow.mockReturnValue(defaultContext({
      supervisedRepos: [{ slug: 'org/repo', path: '/tmp/repo' }],
      selectedRepoSlug: 'org-repo',
      selectRepo,
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    fireEvent.click(screen.getByTestId('repo-option-all'))
    expect(selectRepo).toHaveBeenCalledWith(null)
  })

  it('closes dropdown after selection', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      supervisedRepos: [{ slug: 'org/repo', path: '/tmp/repo' }],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-selector-dropdown')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('repo-option-org-repo'))
    expect(screen.queryByTestId('repo-selector-dropdown')).toBeNull()
  })

  it('closes dropdown on outside click', () => {
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-selector-dropdown')).toBeInTheDocument()
    fireEvent.mouseDown(document.body)
    expect(screen.queryByTestId('repo-selector-dropdown')).toBeNull()
  })

  it('shows empty message when no repos are registered', () => {
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByText('No repos registered')).toBeInTheDocument()
  })

  it('has correct aria attributes on trigger', () => {
    render(<RepoSelector />)
    const trigger = screen.getByTestId('repo-selector-trigger')
    expect(trigger).toHaveAttribute('aria-haspopup', 'listbox')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })

  it('marks selected option with aria-selected', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      supervisedRepos: [{ slug: 'org/repo', path: '/tmp/repo' }],
      selectedRepoSlug: 'org-repo',
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-option-org-repo')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('repo-option-all')).toHaveAttribute('aria-selected', 'false')
  })
})
