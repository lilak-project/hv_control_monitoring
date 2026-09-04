import type { BoardReading, ParamSpec, Snapshot } from "./types"

/**
 * The columns the table opens with: what you check walking past the rack.
 *
 * Everything the boards report stays in the snapshot and one click away --
 * this only decides what is on screen before you ask for more.
 */
export const CORE_PARAMS = ["VMon", "IMon", "V0Set", "I0Set", "Pw", "Status"]

/**
 * Every parameter in the snapshot, in the order the backend ranked them.
 *
 * Boards differ -- the A2551A low-voltage card has Temp and Intck where the
 * A1542HSN has SVMax and ImRange -- so the picker offers the union and each
 * table shows the ones its own board actually has.
 */
export function allParams(snapshot: Snapshot | null): ParamSpec[] {
  if (!snapshot) return []
  const seen = new Map<string, ParamSpec>()
  for (const board of snapshot.boards) {
    for (const spec of board.params) {
      if (!seen.has(spec.name)) seen.set(spec.name, spec)
    }
  }
  return [...seen.values()]
}

/** The specs one board shows, filtered to the chosen columns and kept in board order. */
export function visibleParams(board: BoardReading, chosen: Set<string>): ParamSpec[] {
  return board.params.filter((spec) => chosen.has(spec.name))
}
