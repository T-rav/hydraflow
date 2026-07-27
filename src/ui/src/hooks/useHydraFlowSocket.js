/**
 * Thin compatibility wrapper — re-exports the reducer for tests
 * and provides useHydraFlowSocket as a hook over useHydraFlow.
 *
 * All state management has moved to HydraFlowContext. This wrapper stays so
 * consumers can depend on a socket-shaped hook without reaching into the
 * context module directly.
 */
import { useHydraFlow } from '../context/HydraFlowContext'

export { reducer, initialState } from '../context/HydraFlowContext'

/**
 * useHydraFlowSocket — the HydraFlow context value plus a derived, additive
 * `disconnected` connection signal.
 *
 * The reducer already tracks `connected` (true on WS open, false on close).
 * Task 10 surfaces the inverse as `disconnected` so the OperatorConsole can
 * slide in a non-blocking offline banner without every consumer re-deriving it.
 * This is purely additive: every existing context field passes through
 * unchanged, so current consumers (useTimeline, OperatorConsole) are unaffected.
 */
export function useHydraFlowSocket() {
  const ctx = useHydraFlow()
  return { ...ctx, disconnected: ctx.connected === false }
}
