import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { HumanInputBanner } from '../HumanInputBanner'

describe('HumanInputBanner', () => {
  it('renders nothing when requests is empty', () => {
    const { container } = render(
      <HumanInputBanner requests={{}} onSubmit={() => {}} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows the question and issue number for the first request', () => {
    render(
      <HumanInputBanner
        requests={{ 42: 'What is the expected output?' }}
        onSubmit={() => {}}
      />
    )
    expect(screen.getByText('Issue #42: What is the expected output?')).toBeInTheDocument()
  })

  it('renders only the first request when multiple are present', () => {
    // Use non-numeric string keys to preserve insertion order
    render(
      <HumanInputBanner
        requests={{ 'issue-a': 'First question', 'issue-b': 'Second question' }}
        onSubmit={() => {}}
      />
    )
    expect(screen.getByText(/First question/)).toBeInTheDocument()
    expect(screen.queryByText(/Second question/)).not.toBeInTheDocument()
  })

  it('calls onSubmit with issueNumber and trimmed answer when Send is clicked', () => {
    const onSubmit = vi.fn()
    render(
      <HumanInputBanner
        requests={{ 42: 'Which branch?' }}
        onSubmit={onSubmit}
      />
    )

    fireEvent.change(screen.getByPlaceholderText('Type your response...'), {
      target: { value: '  main  ' },
    })
    fireEvent.click(screen.getByText('Send'))

    expect(onSubmit).toHaveBeenCalledWith('42', 'main')
  })

  it('clears the input after a successful submit', () => {
    render(
      <HumanInputBanner
        requests={{ 42: 'Which branch?' }}
        onSubmit={() => {}}
      />
    )

    const input = screen.getByPlaceholderText('Type your response...')
    fireEvent.change(input, { target: { value: 'main' } })
    fireEvent.click(screen.getByText('Send'))

    expect(input.value).toBe('')
  })

  it('does not call onSubmit when answer is blank or whitespace-only', () => {
    const onSubmit = vi.fn()
    render(
      <HumanInputBanner
        requests={{ 42: 'Which branch?' }}
        onSubmit={onSubmit}
      />
    )

    fireEvent.change(screen.getByPlaceholderText('Type your response...'), {
      target: { value: '   ' },
    })
    fireEvent.click(screen.getByText('Send'))

    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submits on Enter key press', () => {
    const onSubmit = vi.fn()
    render(
      <HumanInputBanner
        requests={{ 10: 'Describe the bug' }}
        onSubmit={onSubmit}
      />
    )

    const input = screen.getByPlaceholderText('Type your response...')
    fireEvent.change(input, { target: { value: 'Stack overflow on large input' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onSubmit).toHaveBeenCalledWith('10', 'Stack overflow on large input')
  })

  it('does not submit on non-Enter key press', () => {
    const onSubmit = vi.fn()
    render(
      <HumanInputBanner
        requests={{ 10: 'Describe the bug' }}
        onSubmit={onSubmit}
      />
    )

    const input = screen.getByPlaceholderText('Type your response...')
    fireEvent.change(input, { target: { value: 'some text' } })
    fireEvent.keyDown(input, { key: 'Tab' })

    expect(onSubmit).not.toHaveBeenCalled()
  })
})
