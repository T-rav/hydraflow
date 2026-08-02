/**
 * Cost view-model for the operator console cost/tokens panel (#10785).
 *
 * Pure `toCostByRepo(raw)` — no fetch, no React. Turns the
 * `/api/diagnostics/cost/by-model-by-repo` payload (repo + per-repo
 * cost-per-model over a rolling 24h window) into a stable shape the panel
 * renders:
 *
 *   {
 *     windowLabel: 'last 24h',
 *     totalCostUsd: number,
 *     totalCostUnknown: boolean,   // any aggregate model unpriced (#9821)
 *     all:   [ ModelRow ],         // cross-repo aggregate, spend-descending
 *     repos: [ { repo, totalCostUsd, byModel: [ ModelRow ] } ],
 *   }
 *
 * where ModelRow = { model, costUsd, costUnknown, calls, tokensIn, tokensOut }.
 *
 * A missing / malformed payload yields the EMPTY view model, never throws — a
 * failed or empty feed leaves the panel rendering its calm empty state.
 */

/** The window label the backend fixes at "last 24h" (kept as the default). */
const WINDOW_LABEL = 'last 24h'

/** Frozen empty view model — the fallback for a missing / malformed payload. */
export const EMPTY_COST_VM = Object.freeze({
  windowLabel: WINDOW_LABEL,
  totalCostUsd: 0,
  totalCostUnknown: false,
  all: Object.freeze([]),
  repos: Object.freeze([]),
})

function num(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/** Map one raw cost-by-model row into a ModelRow. */
function toModelRow(raw) {
  return {
    model: String(raw?.model ?? 'unknown'),
    costUsd: num(raw?.cost_usd),
    costUnknown: Boolean(raw?.cost_unknown),
    calls: num(raw?.calls),
    tokensIn: num(raw?.input_tokens),
    tokensOut: num(raw?.output_tokens),
  }
}

/** Map + sort a raw row list, spend-descending (ties broken by model name). */
function toModelRows(rawRows) {
  if (!Array.isArray(rawRows)) return []
  return rawRows
    .filter(r => r && typeof r === 'object')
    .map(toModelRow)
    .sort((a, b) => b.costUsd - a.costUsd || a.model.localeCompare(b.model))
}

/**
 * @param {unknown} raw The `/cost/by-model-by-repo` payload.
 * @returns {{windowLabel, totalCostUsd, totalCostUnknown, all, repos}}
 */
export function toCostByRepo(raw) {
  if (!raw || typeof raw !== 'object') return EMPTY_COST_VM

  const all = toModelRows(raw.all)
  const repos = Array.isArray(raw.repos)
    ? raw.repos
        .filter(r => r && typeof r === 'object')
        .map(r => {
          const byModel = toModelRows(r.by_model)
          const totalCostUsd = Number.isFinite(Number(r.total_cost_usd))
            ? num(r.total_cost_usd)
            : byModel.reduce((sum, m) => sum + m.costUsd, 0)
          return { repo: String(r.repo ?? ''), totalCostUsd, byModel }
        })
        .sort((a, b) => b.totalCostUsd - a.totalCostUsd || a.repo.localeCompare(b.repo))
    : []

  const totalCostUsd = Number.isFinite(Number(raw.total_cost_usd))
    ? num(raw.total_cost_usd)
    : all.reduce((sum, m) => sum + m.costUsd, 0)

  return {
    windowLabel: String(raw.window_label || WINDOW_LABEL),
    totalCostUsd,
    totalCostUnknown: all.some(m => m.costUnknown),
    all,
    repos,
  }
}

export default toCostByRepo
