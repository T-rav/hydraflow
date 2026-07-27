// Collision-free border builder (#10583).
//
// Inline style objects must never declare the CSS `border` shorthand next to a
// per-side longhand (`borderTop` / `borderRight` / `borderBottom` /
// `borderLeft`): when such an object is spread over — or under — another style
// object conditionally, React drops one side while the shorthand stays, which
// is both a `validateShorthandPropertyCollisionInDev` warning and a real visual
// bug (see #10564 / #10571 / #10579). The structural guard in
// `src/test/borderShorthandScan.js` fails CI if the pattern re-enters the code.
//
// `borderSides` expresses a border entirely through the four per-side
// longhands, so its output is safe to spread into any style object. Two common
// shapes both fall out of it:
//   - edge-only reset (`border: 'none'` + one edge):
//       borderSides({ bottom: `1px solid ${theme.border}` })
//   - box border with an accent edge:
//       borderSides({ fallback: `1px solid ${box}`, left: `3px solid ${accent}` })

/**
 * Build the four per-side border longhands from a spec.
 *
 * @param {object} [spec]
 * @param {string} [spec.top]      Value for `borderTop`.
 * @param {string} [spec.right]    Value for `borderRight`.
 * @param {string} [spec.bottom]   Value for `borderBottom`.
 * @param {string} [spec.left]     Value for `borderLeft`.
 * @param {string} [spec.fallback] Value for any side left unspecified. Defaults
 *   to `'none'`, giving an edge-only reset when a single side is provided.
 * @returns {{borderTop: string, borderRight: string, borderBottom: string, borderLeft: string}}
 *   An object with only per-side longhand keys — never the `border` shorthand.
 */
export function borderSides({ top, right, bottom, left, fallback = 'none' } = {}) {
  return {
    borderTop: top ?? fallback,
    borderRight: right ?? fallback,
    borderBottom: bottom ?? fallback,
    borderLeft: left ?? fallback,
  }
}
