import type { Snapshot } from "./types"

/**
 * What moved between two snapshots.
 *
 * Keyed `slot:channel:param`, so a lookup while rendering a cell is one map
 * hit rather than a search through the baseline. The value kept is the old
 * one -- the new one is already in the row being drawn.
 */
export type Changes = Map<string, number>

export function cellKey(slot: number, channel: number, param: string): string {
  return `${slot}:${channel}:${param}`
}

/**
 * Compare a snapshot against an earlier one.
 *
 * A channel or board that only exists in one of them is not a change: the
 * card was pulled or added, which the board header already says. Only values
 * present on both sides and genuinely different are reported.
 */
export function diffSnapshots(current: Snapshot | null, baseline: Snapshot | null): Changes {
  const changes: Changes = new Map()
  if (!current || !baseline || current.id === baseline.id) return changes

  const before = new Map<string, number>()
  for (const board of baseline.boards) {
    for (const row of board.rows) {
      for (const [param, value] of Object.entries(row.values)) {
        before.set(cellKey(board.slot, row.channel, param), value)
      }
    }
  }

  for (const board of current.boards) {
    for (const row of board.rows) {
      for (const [param, value] of Object.entries(row.values)) {
        const key = cellKey(board.slot, row.channel, param)
        const was = before.get(key)
        if (was !== undefined && was !== value) changes.set(key, was)
      }
    }
  }
  return changes
}

/** Whether any of a row's cells changed -- drives the "changed only" filter. */
export function rowChanged(changes: Changes, slot: number, channel: number, params: string[]): boolean {
  return params.some((param) => changes.has(cellKey(slot, channel, param)))
}
