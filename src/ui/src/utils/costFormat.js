/**
 * Shared cost/token formatters for the operator console cost panel (#10785).
 *
 * Public exports only (no `_`-prefixed cross-module imports, per the wiki):
 * the operator model + panel both format spend the same way through these.
 *
 * The load-bearing rule (#9821): an UNPRICED model must render "unknown", never
 * "$0.00" — a dashboard reads $0 as "cheap", hiding real spend. So `formatUsd`
 * takes an explicit `unknown` flag; a genuinely-zero PRICED cost still renders
 * "$0.00".
 */

/** Coerce to a finite number, else `fallback`. */
function finite(value, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

/**
 * Format a USD cost. `unknown` (the row's `costUnknown` flag) short-circuits to
 * the literal "unknown"; a non-finite cost is treated as unknown too. A tiny
 * but non-zero cost renders "<$0.01" so it never rounds away to "$0.00".
 *
 * @param {number} costUsd
 * @param {{ unknown?: boolean }} [opts]
 * @returns {string}
 */
export function formatUsd(costUsd, { unknown = false } = {}) {
  if (unknown) return 'unknown'
  // Absent cost is unknown, not zero (Number(null) === 0 would fabricate $0.00).
  if (costUsd == null) return 'unknown'
  const n = Number(costUsd)
  if (!Number.isFinite(n)) return 'unknown'
  const abs = Math.abs(n)
  if (abs > 0 && abs < 0.01) return '<$0.01'
  return `$${n.toFixed(2)}`
}

/**
 * Compact token count: 1234 -> "1.2k", 2_500_000 -> "2.5M". Non-finite or
 * non-positive -> "0".
 *
 * @param {number} value
 * @returns {string}
 */
export function formatTokens(value) {
  const n = finite(value, 0)
  if (n <= 0) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(Math.round(n))
}
