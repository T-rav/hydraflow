import { describe, it, expect } from 'vitest'
import { borderSides } from '../borders'

describe('borderSides — collision-free per-side border builder (#10583)', () => {
  it('emits the four per-side longhands and never the `border` shorthand', () => {
    const style = borderSides({ bottom: '1px solid #333' })
    expect(Object.keys(style).sort()).toEqual(
      ['borderBottom', 'borderLeft', 'borderRight', 'borderTop']
    )
    expect(style).not.toHaveProperty('border')
  })

  it('fills unspecified sides with `none` by default (edge-only reset)', () => {
    expect(borderSides({ bottom: '1px solid #333' })).toEqual({
      borderTop: 'none',
      borderRight: 'none',
      borderBottom: '1px solid #333',
      borderLeft: 'none',
    })
  })

  it('uses a custom fallback for the unspecified sides (box border + accent edge)', () => {
    expect(borderSides({ fallback: '1px solid grey', left: '3px solid blue' })).toEqual({
      borderTop: '1px solid grey',
      borderRight: '1px solid grey',
      borderBottom: '1px solid grey',
      borderLeft: '3px solid blue',
    })
  })

  it('lets an explicit side override the fallback', () => {
    const style = borderSides({ fallback: '1px solid grey', top: '2px dashed red' })
    expect(style.borderTop).toBe('2px dashed red')
    expect(style.borderRight).toBe('1px solid grey')
  })

  it('defaults every side to `none` when called with no spec', () => {
    expect(borderSides()).toEqual({
      borderTop: 'none',
      borderRight: 'none',
      borderBottom: 'none',
      borderLeft: 'none',
    })
  })
})
