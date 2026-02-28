import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ANNOTATION_COLORS } from '../../constants'

const { ReportIssueModal } = await import('../ReportIssueModal')

const defaultProps = {
  isOpen: true,
  screenshotDataUrl: null,
  onSubmit: vi.fn(),
  onClose: vi.fn(),
}

describe('ReportIssueModal', () => {
  it('renders nothing when isOpen is false', () => {
    render(<ReportIssueModal {...defaultProps} isOpen={false} />)
    expect(screen.queryByTestId('report-modal-overlay')).toBeNull()
  })

  it('renders overlay and card when isOpen is true', () => {
    render(<ReportIssueModal {...defaultProps} />)
    expect(screen.getByTestId('report-modal-overlay')).toBeInTheDocument()
    expect(screen.getByTestId('report-modal-card')).toBeInTheDocument()
  })

  it('renders 6 color swatches', () => {
    render(<ReportIssueModal {...defaultProps} />)
    ANNOTATION_COLORS.forEach((c) => {
      expect(screen.getByTestId(`color-swatch-${c.key}`)).toBeInTheDocument()
    })
  })

  it('submit button is disabled with empty description', () => {
    render(<ReportIssueModal {...defaultProps} />)
    const submitBtn = screen.getByTestId('report-submit')
    expect(submitBtn).toBeDisabled()
  })

  it('submit calls onSubmit with description', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<ReportIssueModal {...defaultProps} onSubmit={onSubmit} />)
    const textarea = screen.getByTestId('report-description')
    fireEvent.change(textarea, { target: { value: 'Something is broken' } })
    const submitBtn = screen.getByTestId('report-submit')
    expect(submitBtn).not.toBeDisabled()
    fireEvent.click(submitBtn)
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ description: 'Something is broken' })
    )
  })

  it('cancel calls onClose', () => {
    const onClose = vi.fn()
    render(<ReportIssueModal {...defaultProps} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('report-cancel'))
    expect(onClose).toHaveBeenCalled()
  })

  it('backdrop click calls onClose', () => {
    const onClose = vi.fn()
    render(<ReportIssueModal {...defaultProps} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('report-modal-overlay'))
    expect(onClose).toHaveBeenCalled()
  })
})
