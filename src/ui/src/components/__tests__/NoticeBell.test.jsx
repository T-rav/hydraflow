import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { NoticeBell } from '../NoticeBell'

const notice = (id, message, source = 'epic_monitor') => ({ id, message, source })

describe('NoticeBell (#11306)', () => {
  it('renders a muted bell with no dropdown when there are no advisories', () => {
    render(<NoticeBell notices={[]} />)
    expect(screen.getByTestId('notice-bell-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('notice-bell-dropdown')).not.toBeInTheDocument()
  })

  it('shows the advisory count on the badge', () => {
    render(<NoticeBell notices={[notice('a', 'Epic #1 is stale'), notice('b', 'Epic #2 is stale')]} />)
    expect(screen.getByTestId('notice-bell-count')).toHaveTextContent('2')
  })

  it('opens a dropdown listing each notice with its source', () => {
    render(<NoticeBell notices={[notice('a', 'Epic #10914 is stale')]} />)
    fireEvent.click(screen.getByTestId('notice-bell'))
    expect(screen.getByTestId('notice-bell-dropdown')).toBeInTheDocument()
    expect(screen.getByText('Epic #10914 is stale')).toBeInTheDocument()
    expect(screen.getByText('epic_monitor')).toBeInTheDocument()
  })

  it('dismisses a single notice by id', () => {
    const onDismiss = vi.fn()
    render(<NoticeBell notices={[notice('a', 'x')]} onDismiss={onDismiss} />)
    fireEvent.click(screen.getByTestId('notice-bell'))
    fireEvent.click(screen.getByTestId('notice-bell-dismiss'))
    expect(onDismiss).toHaveBeenCalledWith('a')
  })

  it('clears all notices', () => {
    const onDismissAll = vi.fn()
    render(<NoticeBell notices={[notice('a', 'x'), notice('b', 'y')]} onDismissAll={onDismissAll} />)
    fireEvent.click(screen.getByTestId('notice-bell'))
    fireEvent.click(screen.getByTestId('notice-bell-clear-all'))
    expect(onDismissAll).toHaveBeenCalled()
  })
})
