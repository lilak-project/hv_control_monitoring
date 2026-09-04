import type { ChannelRow, ParamSpec } from "./types"

/**
 * How many decimals a numeric column gets.
 *
 * Taken from what the board declares about the column, never from the value,
 * so a column does not change width as a channel ramps.
 *
 * Currents get three places whatever their range: a leakage reading lives in
 * the bottom thousandth of a 100 uA scale, and two places would round most of
 * an idle crate to 0.00. Everything else follows its range -- 0-500 V to two
 * places, a 0-1000 s trip time to one.
 */
function decimals(spec: ParamSpec): number {
  if (spec.unit.endsWith("A")) return 3
  const span = spec.max ?? 0
  if (span >= 1000) return 1
  if (span >= 10) return 2
  return 3
}

/** One cell, as text.  Never returns an empty string -- a gap must look deliberate. */
export function formatValue(spec: ParamSpec, value: number | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "–"
  switch (spec.type) {
    case "numeric":
      return value.toFixed(decimals(spec))
    case "onoff":
      return value ? spec.on_state : spec.off_state
    case "chstatus":
    case "bdstatus":
      return value === 0 ? "ok" : `0x${value.toString(16).toUpperCase()}`
    case "binary":
      return value === 0 ? "–" : `0x${value.toString(16).toUpperCase()}`
    default:
      return String(value)
  }
}

/** The column heading: the parameter, and the unit it is in. */
export function columnLabel(spec: ParamSpec): string {
  return spec.unit ? `${spec.name} ${spec.unit}` : spec.name
}

/** "20:12:43" -- the archive is browsed by day, so a row only needs the time. */
export function clockTime(isoLocal: string): string {
  return isoLocal.slice(11, 19) || isoLocal
}

/** "2026-08-29 20:12:43" for the toolbar, where the day is not otherwise on screen. */
export function stampTime(isoLocal: string): string {
  return isoLocal.slice(0, 19).replace("T", " ") || isoLocal
}

/** "2026-08-29 (Sat)" -- the weekday is how people remember which run was which. */
export function dayLabel(day: string): string {
  const date = new Date(`${day}T00:00:00`)
  if (Number.isNaN(date.getTime())) return day
  return `${day} (${date.toLocaleDateString(undefined, { weekday: "short" })})`
}

/** How long ago, coarse enough not to need a ticking clock. */
export function ago(isoUtc: string): string {
  const seconds = (Date.now() - new Date(isoUtc).getTime()) / 1000
  if (!Number.isFinite(seconds) || seconds < 0) return ""
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86400)}d ago`
}

/** What a row is called when it has no name in the crate. */
export function channelLabel(row: ChannelRow): string {
  return row.name || "–"
}
