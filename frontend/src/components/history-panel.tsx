import { Select } from "@mantine/core"

import { clockTime, dayLabel } from "@/lib/format"
import type { Day, SnapshotSummary } from "@/lib/types"

/** The archive, newest first, grouped under the day each snapshot was taken. */
export function HistoryPanel({
  entries,
  days,
  day,
  currentId,
  baselineId,
  open,
  onSelectDay,
  onOpen,
  onCompare,
}: {
  entries: SnapshotSummary[]
  days: Day[]
  /** null means "the most recent, whatever day they fell on". */
  day: string | null
  currentId: string | null
  baselineId: string | null
  open: boolean
  onSelectDay: (day: string | null) => void
  onOpen: (id: string) => void
  onCompare: (id: string) => void
}) {
  const total = days.reduce((sum, entry) => sum + entry.count, 0)

  return (
    <aside className={open ? "history is-open" : "history"}>
      <div className="history-head">
        <Select
          aria-label="Day"
          data={[
            { value: "", label: `Recent (${total} total)` },
            ...days.map((entry) => ({
              value: entry.day,
              label: `${dayLabel(entry.day)} · ${entry.count}`,
            })),
          ]}
          value={day ?? ""}
          onChange={(value) => onSelectDay(value || null)}
          allowDeselect={false}
          comboboxProps={{ width: 240, position: "bottom-start" }}
          style={{ flex: 1 }}
        />
      </div>

      {entries.length === 0 ? (
        <div className="empty">
          No snapshots yet.
          <br />
          Press Snapshot to take one.
        </div>
      ) : (
        groupByDay(entries).map(([groupDay, group]) => (
          <div key={groupDay}>
            <div className="history-day">
              {dayLabel(groupDay)} · {group.length}
            </div>
            {group.map((entry) => {
              const classes = ["history-row"]
              if (entry.id === currentId) classes.push("is-current")
              if (entry.id === baselineId) classes.push("is-baseline")
              return (
                <div key={entry.id} className={classes.join(" ")}>
                  <button
                    type="button"
                    className="history-open"
                    onClick={() => onOpen(entry.id)}
                    title={`${entry.taken_at_local} · ${entry.channels} channels · ${entry.elapsed_ms} ms`}
                  >
                    <span className="tabular">{clockTime(entry.taken_at_local)}</span>
                    <span className={entry.powered > 0 ? "on" : "dim"}>{entry.powered} on</span>
                    {entry.faults > 0 ? <span className="fault">{entry.faults} flt</span> : null}
                    {entry.errors > 0 ? <span className="fault">err</span> : null}
                    {entry.note ? <span className="meta history-note">{entry.note}</span> : null}
                  </button>
                  <button
                    type="button"
                    className="history-compare"
                    onClick={() => onCompare(entry.id)}
                    title="Compare the open snapshot against this one"
                    aria-label={`Compare against ${entry.taken_at_local}`}
                  >
                    Δ
                  </button>
                </div>
              )
            })}
          </div>
        ))
      )}
    </aside>
  )
}

/** Ids start with the local date, so the day is the first eight characters. */
function groupByDay(entries: SnapshotSummary[]): [string, SnapshotSummary[]][] {
  const groups = new Map<string, SnapshotSummary[]>()
  for (const entry of entries) {
    const key = `${entry.id.slice(0, 4)}-${entry.id.slice(4, 6)}-${entry.id.slice(6, 8)}`
    const bucket = groups.get(key)
    if (bucket) bucket.push(entry)
    else groups.set(key, [entry])
  }
  return [...groups.entries()]
}
