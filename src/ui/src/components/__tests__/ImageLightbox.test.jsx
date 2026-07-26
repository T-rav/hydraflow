import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ImageLightbox } from '../ImageLightbox'

const SRC = 'https://ci.example.com/screens/login-actual.png'

describe('ImageLightbox', () => {
  it('renders nothing when no src is provided', () => {
    render(<ImageLightbox src="" onClose={() => {}} />)
    expect(screen.queryByTestId('image-lightbox-overlay')).toBeNull()
  })

  it('renders the full-resolution image when src is provided', () => {
    render(<ImageLightbox src={SRC} alt="login actual" onClose={() => {}} />)
    const img = screen.getByTestId('image-lightbox-img')
    expect(img).toBeInTheDocument()
    expect(img.getAttribute('src')).toBe(SRC)
    expect(img.getAttribute('alt')).toBe('login actual')
  })

  it('scales the image to the viewport while preserving aspect ratio', () => {
    render(<ImageLightbox src={SRC} onClose={() => {}} />)
    const img = screen.getByTestId('image-lightbox-img')
    // Preserve aspect ratio: never distort, only contain within the viewport.
    expect(img.style.objectFit).toBe('contain')
    expect(img.style.maxWidth).toBe('95vw')
    // Auto dimensions keep the native aspect ratio intact.
    expect(img.style.width).toBe('auto')
    expect(img.style.height).toBe('auto')
  })

  it('shows an "open original" affordance pointing at the full-res image', () => {
    render(<ImageLightbox src={SRC} onClose={() => {}} />)
    const link = screen.getByTestId('image-lightbox-open-original')
    expect(link.getAttribute('href')).toBe(SRC)
    expect(link.getAttribute('target')).toBe('_blank')
  })

  it('renders the caption when provided', () => {
    render(<ImageLightbox src={SRC} caption="login — Actual" onClose={() => {}} />)
    expect(screen.getByTestId('image-lightbox-caption')).toHaveTextContent('login — Actual')
  })

  it('calls onClose when the close button is clicked', () => {
    const onClose = vi.fn()
    render(<ImageLightbox src={SRC} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('image-lightbox-close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when the backdrop is clicked', () => {
    const onClose = vi.fn()
    render(<ImageLightbox src={SRC} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('image-lightbox-overlay'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not close when the image itself is clicked', () => {
    const onClose = vi.fn()
    render(<ImageLightbox src={SRC} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('image-lightbox-img'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose when Escape is pressed', () => {
    const onClose = vi.fn()
    render(<ImageLightbox src={SRC} onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
