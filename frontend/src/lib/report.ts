import { visibleParams } from "./columns"
import type { Changes } from "./diff"
import { describeFilter, matchesFilter, type RowFilter } from "./filter"
import { columnLabel, formatValue, stampTime } from "./format"
import type { ChannelRow, ParamSpec, Snapshot } from "./types"

/**
 * The channels on screen, as fixed-width text.
 *
 * For pasting into the logbook or a chat window, where a CSV is unreadable and
 * a screenshot cannot be searched. What is copied is exactly what the table
 * shows -- the same rows, the same columns, the same rounding -- so a pasted
 * block and the page never disagree.
 */

/** One cell, worded the way the table words it. */
function cellText(spec: ParamSpec, row: ChannelRow): string {
  const value = row.values[spec.name]
  if (spec.type === "chstatus" || spec.type === "bdstatus") {
    // The table trades the hex for the named bits; a log entry wants the same.
    const raw = typeof value === "number" ? value : 0
    if (raw === 0) return "ok"
    const flags = row.status?.flags ?? []
    return flags.length > 0 ? flags.join(", ") : `0x${raw.toString(16).toUpperCase()}`
  }
  return formatValue(spec, value)
}

/** Numbers line up on the right, words on the left -- as in the table. */
function alignsRight(spec: ParamSpec): boolean {
  return spec.type === "numeric" || spec.type === "binary"
}

function pad(text: string, width: number, right: boolean): string {
  return right ? text.padStart(width) : text.padEnd(width)
}

/** Column widths from the widest thing in each column, header included. */
function layout(header: string[], body: string[][]): number[] {
  return header.map((title, index) =>
    body.reduce((widest, cells) => Math.max(widest, cells[index].length), title.length),
  )
}

export function snapshotText(
  snapshot: Snapshot | null,
  chosen: Set<string>,
  changes: Changes,
  filter: RowFilter,
): string {
  if (!snapshot) return ""

  const lines: string[] = [
    `HV ${snapshot.label} · ${snapshot.host} · ${snapshot.system_type}`,
    `${stampTime(snapshot.taken_at_local)}`,
  ]
  const described = describeFilter(filter)
  if (described) lines.push(`showing: ${described}`)

  for (const entry of snapshot.errors) {
    lines.push(`slot ${entry.slot}: ${entry.error}`)
  }

  let shown = 0
  for (const board of snapshot.boards) {
    const params = visibleParams(board, chosen)
    const rows = board.rows.filter((row) => matchesFilter(row, board, filter, changes, params))
    // A board the filter emptied is left out entirely: its header alone would
    // read as "these channels are fine" rather than "none were asked for".
    if (rows.length === 0) continue
    shown += rows.length

    const header = ["ch", "name", ...params.map(columnLabel)]
    const body = rows.map((row) => [
      String(row.channel),
      row.name || "-",
      ...params.map((spec) => cellText(spec, row)),
    ])
    const widths = layout(header, body)
    const right = [true, false, ...params.map(alignsRight)]

    lines.push("")
    lines.push(
      `slot ${board.slot} · ${board.model} · sn ${board.serial} · fw ${board.firmware} · ` +
        `${board.channels} ch · ${board.powered} on` +
        (board.faults > 0 ? ` · ${board.faults} fault` : "") +
        // The counts above are the whole board's, as in the table header, so a
        // trimmed list has to say so or it reads as a board with fewer channels.
        (rows.length === board.rows.length ? "" : ` · showing ${rows.length} of ${board.rows.length}`),
    )
    for (const cells of [header, ...body]) {
      lines.push(cells.map((cell, index) => pad(cell, widths[index], right[index])).join("  ").trimEnd())
    }
  }

  if (shown === 0) lines.push("", "no channel matches the filter")
  return lines.join("\n")
}
