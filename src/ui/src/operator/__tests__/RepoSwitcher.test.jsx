import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// RepoSwitcher lets the operator jump sideways between repos while PRESERVING
// the current stage/item drill depth (epic #10556, Task 9), and exposes
// "+ Add repo" which opens the EXISTING RegisterRepoDialog. It is prop-driven so
// it renders without a HydraFlowProvider; the RegisterRepoDialog it lazily mounts
// on demand is the only context consumer, so we mock it here to isolate the
// switcher's own behaviour.

const dialogRenders = vi.fn()
vi.mock('../../components/RegisterRepoDialog', () => ({
  RegisterRepoDialog: ({ isOpen, onClose }) => {
    dialogRenders(isOpen)
    return isOpen
      ? <div data-testid="mock-register-dialog"><button onClick={onClose}>close</button></div>
      : null
  },
}))

const { RepoSwitcher } = await import('../RepoSwitcher')

function makeRepos() {
  return [
    { slug: 'acme/app', name: 'acme/app', running: true },
    { slug: 'acme/lib', name: 'acme/lib', running: false },
  ]
}

describe('RepoSwitcher', () => {
  beforeEach(() => {
    dialogRenders.mockClear()
  })

  it('renders a trigger showing the current repo', () => {
    render(<RepoSwitcher repos={makeRepos()} current="acme/app" select={() => {}} />)
    expect(screen.getByTestId('repo-switcher-trigger')).toHaveTextContent('acme/app')
  })

  it('shows "All repos" in the trigger when no repo is selected', () => {
    render(<RepoSwitcher repos={makeRepos()} current={null} select={() => {}} />)
    expect(screen.getByTestId('repo-switcher-trigger')).toHaveTextContent('All repos')
  })

  it('opens a dropdown listing the other repos when the trigger is clicked', () => {
    render(<RepoSwitcher repos={makeRepos()} current="acme/app" select={() => {}} />)
    fireEvent.click(screen.getByTestId('repo-switcher-trigger'))
    expect(screen.getByTestId('repo-switcher-dropdown')).toBeInTheDocument()
    expect(screen.getByTestId('repo-switcher-option-acme/lib')).toBeInTheDocument()
  })

  it('preserves stage/item depth when switching repos', () => {
    const select = vi.fn()
    render(
      <RepoSwitcher
        repos={makeRepos()}
        current="acme/app"
        stage="implement"
        item="55"
        select={select}
      />,
    )
    fireEvent.click(screen.getByTestId('repo-switcher-trigger'))
    fireEvent.click(screen.getByTestId('repo-switcher-option-acme/lib'))
    // Repo first (resets depth in the hook), then the depth is re-applied.
    expect(select).toHaveBeenNthCalledWith(1, 'repo', 'acme/lib')
    expect(select).toHaveBeenNthCalledWith(2, 'stage', 'implement')
    expect(select).toHaveBeenNthCalledWith(3, 'item', '55')
  })

  it('does not re-apply depth that is not set', () => {
    const select = vi.fn()
    render(<RepoSwitcher repos={makeRepos()} current="acme/app" select={select} />)
    fireEvent.click(screen.getByTestId('repo-switcher-trigger'))
    fireEvent.click(screen.getByTestId('repo-switcher-option-acme/lib'))
    expect(select).toHaveBeenCalledTimes(1)
    expect(select).toHaveBeenCalledWith('repo', 'acme/lib')
  })

  it('pops to the overview via select("repo", null) from the "All repos" entry', () => {
    const select = vi.fn()
    render(<RepoSwitcher repos={makeRepos()} current="acme/app" stage="plan" select={select} />)
    fireEvent.click(screen.getByTestId('repo-switcher-trigger'))
    fireEvent.click(screen.getByTestId('repo-switcher-all'))
    expect(select).toHaveBeenCalledWith('repo', null)
    // Popping to "All repos" clears depth — it must NOT re-apply the stage.
    expect(select).toHaveBeenCalledTimes(1)
  })

  it('opens the existing RegisterRepoDialog from "+ Add repo"', () => {
    render(<RepoSwitcher repos={makeRepos()} current="acme/app" select={() => {}} />)
    // Dialog is not mounted until requested.
    expect(screen.queryByTestId('mock-register-dialog')).toBeNull()
    fireEvent.click(screen.getByTestId('repo-switcher-trigger'))
    fireEvent.click(screen.getByTestId('repo-switcher-add'))
    expect(screen.getByTestId('mock-register-dialog')).toBeInTheDocument()
  })

  it('closes the dropdown after a switch', () => {
    render(<RepoSwitcher repos={makeRepos()} current="acme/app" select={() => {}} />)
    fireEvent.click(screen.getByTestId('repo-switcher-trigger'))
    expect(screen.getByTestId('repo-switcher-dropdown')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('repo-switcher-option-acme/lib'))
    expect(screen.queryByTestId('repo-switcher-dropdown')).toBeNull()
  })

  it('marks the current repo option as active', () => {
    render(<RepoSwitcher repos={makeRepos()} current="acme/app" select={() => {}} />)
    fireEvent.click(screen.getByTestId('repo-switcher-trigger'))
    expect(screen.getByTestId('repo-switcher-option-acme/app')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('repo-switcher-option-acme/lib')).toHaveAttribute('aria-selected', 'false')
  })
})
