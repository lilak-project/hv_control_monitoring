import { rowChanged, type Changes } from "./diff"
import type { BoardReading, ChannelRow, ParamSpec } from "./types"

export interface RowFilter {
  /** Matches the channel name or number.  Empty shows everything. */
  text: string
  changedOnly: boolean
  poweredOnly: boolean
  faultsOnly: boolean
}

/**
 * Whether a channel is on screen.
 *
 * Lives here rather than in the table because the copy button has to pick the
 * same rows the operator is looking at -- two answers to "which channels?"
 * would put something on the clipboard that is not on screen.
 */
export function matchesFilter(
  row: ChannelRow,
  board: BoardReading,
  filter: RowFilter,
  changes: Changes,
  params: ParamSpec[],
): boolean {
  if (filter.poweredOnly && row.values.Pw !== 1) return false
  if (filter.faultsOnly && !row.status?.fault) return false
  if (filter.changedOnly && !rowChanged(changes, board.slot, row.channel, params.map((p) => p.name))) {
    return false
  }
  const text = filter.text.trim().toLowerCase()
  if (!text) return true
  return row.name.toLowerCase().includes(text) || String(row.channel) === text
}

/** How the filter reads in one line -- the copy carries it so a pasted table explains itself. */
export function describeFilter(filter: RowFilter): string {
  const parts: string[] = []
  if (filter.text.trim()) parts.push(`matching "${filter.text.trim()}"`)
  if (filter.poweredOnly) parts.push("on only")
  if (filter.faultsOnly) parts.push("faults only")
  if (filter.changedOnly) parts.push("changed only")
  return parts.join(", ")
}
