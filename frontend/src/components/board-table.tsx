import { Fragment } from "react"

import { cellKey, type Changes } from "@/lib/diff"
import { matchesFilter, type RowFilter } from "@/lib/filter"
import { columnLabel, formatValue } from "@/lib/format"
import { visibleParams } from "@/lib/columns"
import type { BoardReading, ChannelRow, ParamSpec } from "@/lib/types"

/** One populated slot: its identity, then a row per channel. */
export function BoardTable({
  board,
  chosen,
  changes,
  filter,
}: {
  board: BoardReading
  chosen: Set<string>
  changes: Changes
  filter: RowFilter
}) {
  const params = visibleParams(board, chosen)
  const rows = board.rows.filter((row) => matchesFilter(row, board, filter, changes, params))

  return (
    <section className="board">
      <header className="board-head">
        <span className="board-slot">slot {board.slot}</span>
        <span>{board.model}</span>
        <span className="meta">{board.description}</span>
        <span className="meta">
          sn {board.serial} · fw {board.firmware} · {board.channels} ch
        </span>
        <span className="meta">
          {board.powered > 0 ? <b className="on">{board.powered} on</b> : "0 on"}
          {board.faults > 0 ? <b className="fault"> · {board.faults} fault</b> : null}
        </span>
        {board.unreadable_params.length > 0 ? (
          <span className="meta" title="The board declares these but would not return a value.">
            unreadable: {board.unreadable_params.join(", ")}
          </span>
        ) : null}
        {rows.length !== board.rows.length ? (
          <span className="meta">
            showing {rows.length} of {board.rows.length}
          </span>
        ) : null}
      </header>

      {rows.length === 0 ? (
        <div className="empty">no channel on this board matches the filter</div>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th className="stick col-ch">ch</th>
              <th className="stick col-name">name</th>
              {params.map((spec) => (
                <th key={spec.name} title={describeParam(spec)}>
                  {columnLabel(spec)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.channel} className={row.status?.fault ? "row-fault" : undefined}>
                <td className="stick col-ch tabular">{row.channel}</td>
                <td className="stick col-name" title={row.name || undefined}>
                  {row.name || <span className="dim">–</span>}
                </td>
                {params.map((spec) => (
                  <Cell
                    key={spec.name}
                    spec={spec}
                    row={row}
                    slot={board.slot}
                    changes={changes}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

/** The column heading's tooltip: what the board says about this parameter. */
function describeParam(spec: ParamSpec): string {
  const parts: string[] = [spec.type]
  if (spec.mode === "rw") parts.push("settable on the crate")
  if (spec.min !== null && spec.max !== null) {
    parts.push(`${spec.min}…${spec.max}${spec.unit ? ` ${spec.unit}` : ""}`)
  }
  return `${spec.name} — ${parts.join(", ")}`
}

function Cell({
  spec,
  row,
  slot,
  changes,
}: {
  spec: ParamSpec
  row: ChannelRow
  slot: number
  changes: Changes
}) {
  const value = row.values[spec.name]
  const previous = changes.get(cellKey(slot, row.channel, spec.name))
  const classes = ["tabular"]
  if (previous !== undefined) classes.push("changed")

  let title: string | undefined
  if (previous !== undefined) title = `was ${formatValue(spec, previous)}`

  let content: React.ReactNode = formatValue(spec, value)

  if (spec.type === "onoff") {
    classes.push(value ? "on" : "off")
  } else if (spec.type === "chstatus" || spec.type === "bdstatus") {
    // The named bits, not the hex: "Ramp up" is what an operator needs. The
    // raw word stays on the tooltip because a low-voltage board numbers its
    // status bits differently from the HV cards these names come from.
    const status = row.status
    const raw = typeof value === "number" ? value : 0
    title = [title, `0x${raw.toString(16).toUpperCase()}`].filter(Boolean).join(" · ")
    classes.push("status-flags")
    if (status?.fault) classes.push("fault")
    content =
      raw === 0 ? (
        <span className="dim">ok</span>
      ) : (
        (status?.flags ?? []).map((flag, index) => (
          <Fragment key={flag}>
            {index > 0 ? ", " : ""}
            {flag}
          </Fragment>
        ))
      )
    if (raw !== 0 && (status?.flags.length ?? 0) === 0) content = `0x${raw.toString(16).toUpperCase()}`
  }

  return (
    <td className={classes.join(" ")} title={title}>
      {content}
    </td>
  )
}
