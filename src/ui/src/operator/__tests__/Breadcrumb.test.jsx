import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Breadcrumb } from '../Breadcrumb'

// The Breadcrumb (epic #10556, Task 8) renders the root-first crumb array from
// `useOperatorSelection` (Task 2) as a clickable trail
// (`‹ All repos › repo ▾ › stage › item`). Each non-terminal segment carries the
// exact `select(kind, value)` args needed to "pop" the selection back to that
// depth; the terminal segment is the current location and is not a link.

// A breadcrumb literal shaped exactly like `buildBreadcrumb(...)` output — root
// first. Keeping it a literal decouples this component test from the hook's
// internals.
function makeBreadcrumb() {
  return [
    { kind: 'repo', label: 'All repos', value: null },
    { kind: 'repo', label: 'acme/web', value: 'acme/web' },
    { kind: 'stage', label: 'Plan', value: 'plan' },
    { kind: 'item', label: '#42', value: '42' },
  ]
}

describe('Breadcrumb', () => {
  it('renders one segment per crumb, in root-first order', () => {
    render(<Breadcrumb breadcrumb={makeBreadcrumb()} select={() => {}} />)
    expect(screen.getByTestId('operator-breadcrumb')).toBeInTheDocument()
    for (const label of ['All repos', 'acme/web', 'Plan', '#42']) {
      expect(screen.getByTestId('operator-breadcrumb')).toHaveTextContent(label)
    }
  })

  it('renders non-terminal segments as buttons and the terminal segment as the current location', () => {
    render(<Breadcrumb breadcrumb={makeBreadcrumb()} select={() => {}} />)
    // First three crumbs are navigable buttons.
    expect(screen.getByTestId('breadcrumb-crumb-0').tagName).toBe('BUTTON')
    expect(screen.getByTestId('breadcrumb-crumb-2').tagName).toBe('BUTTON')
    // The last crumb is the current depth — marked aria-current, not a button.
    const current = screen.getByTestId('breadcrumb-crumb-3')
    expect(current.tagName).not.toBe('BUTTON')
    expect(current).toHaveAttribute('aria-current', 'page')
  })

  it('calls select(kind, value) to pop to that depth when a segment is clicked', () => {
    const select = vi.fn()
    render(<Breadcrumb breadcrumb={makeBreadcrumb()} select={select} />)
    // Jump up to the repo depth (drops stage + item beneath it).
    fireEvent.click(screen.getByTestId('breadcrumb-crumb-1'))
    expect(select).toHaveBeenCalledWith('repo', 'acme/web')
    // Jump up to the stage depth (drops item).
    fireEvent.click(screen.getByTestId('breadcrumb-crumb-2'))
    expect(select).toHaveBeenCalledWith('stage', 'plan')
  })

  it('pops all the way to root ("All repos" → select("repo", null))', () => {
    const select = vi.fn()
    render(<Breadcrumb breadcrumb={makeBreadcrumb()} select={select} />)
    fireEvent.click(screen.getByTestId('breadcrumb-crumb-0'))
    expect(select).toHaveBeenCalledWith('repo', null)
  })

  it('shows a switcher caret on the selected-repo segment (Task-9 affordance)', () => {
    render(<Breadcrumb breadcrumb={makeBreadcrumb()} select={() => {}} />)
    // The concrete repo crumb (has a value) carries the ▾ switcher affordance;
    // the "All repos" root and non-repo crumbs do not.
    expect(screen.getByTestId('breadcrumb-crumb-1')).toHaveTextContent('▾')
    expect(screen.getByTestId('breadcrumb-crumb-0')).not.toHaveTextContent('▾')
    expect(screen.getByTestId('breadcrumb-crumb-2')).not.toHaveTextContent('▾')
  })

  it('does not crash on an empty or missing breadcrumb', () => {
    const { container } = render(<Breadcrumb breadcrumb={[]} select={() => {}} />)
    expect(container.querySelector('[data-testid="operator-breadcrumb"]')).toBeInTheDocument()
    // A single-crumb (root only) trail renders just the current location.
    render(<Breadcrumb select={() => {}} />)
  })
})
