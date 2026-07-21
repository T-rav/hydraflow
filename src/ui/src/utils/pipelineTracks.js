import { PIPELINE_STAGES, PRODUCT_TRACK_KEYS } from '../constants'

// Terminal end-states = pipeline stages with no processing role and no config
// knob (hitl, merged). After REVIEW an issue forks to a human OR gets merged —
// never both — so these render as parallel arms of a fork, not a linear chain
// (#9224). Derived from PIPELINE_STAGES so adding/removing a terminal needs no
// edit at any call site. Single source of truth for BOTH the Header pipeline
// row and StreamView's PipelineFlow (#9564).
export const TERMINAL_TRACK_KEYS = new Set(
  PIPELINE_STAGES.filter(s => !s.role && !s.configKey).map(s => s.key)
)

/** True if `key` is a product-discovery track stage (branches off triage). */
export function isProductStage(key) {
  return PRODUCT_TRACK_KEYS.has(key)
}

/** True if `key` is a terminal end-state (forks off REVIEW: hitl / merged). */
export function isTerminalStage(key) {
  return TERMINAL_TRACK_KEYS.has(key)
}

/**
 * Split an array of stage-bearing items (in PIPELINE_STAGES order) into the
 * pipeline's topology tracks. This is the ONE place that owns the
 * triage / product-fork / linear / terminal-fork partition — both Header's
 * compact pipeline row and StreamView's larger PipelineFlow derive their layout
 * from this, so the two renderers can no longer drift (#9564).
 *
 * Returns:
 *   - triage:     the single triage junction item, or null if absent
 *   - product:    the discover→shape product-fork branch (top arm off triage)
 *   - postTriage: linear main-track items after triage, excluding terminals
 *   - terminal:   the hitl/merged fork off REVIEW
 *   - main:       every non-product item (triage + postTriage + terminal), in order
 *
 * @param {Array} items  Stage-bearing items in PIPELINE_STAGES order.
 * @param {(item: any) => string} getKey  Maps an item to its stage key.
 *   Defaults to `item.key` (Header's {key,count} shape); StreamView passes
 *   `g => g.stage.key` for its {stage,issues} groups.
 */
export function splitPipelineTracks(items, getKey = (item) => item.key) {
  const safeItems = items || []
  const main = safeItems.filter(item => !isProductStage(getKey(item)))
  const product = safeItems.filter(item => isProductStage(getKey(item)))
  const triage = main.find(item => getKey(item) === 'triage') ?? null
  const postTriage = main.filter(
    item => getKey(item) !== 'triage' && !isTerminalStage(getKey(item))
  )
  const terminal = main.filter(item => isTerminalStage(getKey(item)))
  return { triage, product, postTriage, terminal, main }
}
