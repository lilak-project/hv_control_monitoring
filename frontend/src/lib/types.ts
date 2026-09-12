/** The shapes the backend sends.  Mirrors `backend/app/` -- keep them in step. */

export type ParamType = "numeric" | "onoff" | "chstatus" | "bdstatus" | "binary" | "string" | "enum"

/** One column, as the board itself describes it. */
export interface ParamSpec {
  name: string
  type: ParamType
  /** "ro" | "wo" | "rw" -- this service only ever reads. */
  mode: string
  /** Already carries the SI prefix: IMon on an A1542HSN reads "µA". */
  unit: string
  exp: number
  min: number | null
  max: number | null
  on_state: string
  off_state: string
}

export type ParamValue = number

export interface ChannelStatus {
  raw: number
  flags: string[]
  fault: boolean
}

export interface ChannelRow {
  channel: number
  /** The name typed into the crate.  Often blank. */
  name: string
  values: Record<string, ParamValue>
  status?: ChannelStatus
}

export interface BoardReading {
  slot: number
  model: string
  description: string
  serial: number
  firmware: string
  channels: number
  params: ParamSpec[]
  rows: ChannelRow[]
  powered: number
  faults: number
  unreadable_params: string[]
}

export interface Snapshot {
  id: string
  crate: string
  label: string
  host: string
  system_type: string
  /** UTC, ISO 8601. */
  taken_at: string
  /** Server local time, ISO 8601 with offset -- what the page shows. */
  taken_at_local: string
  elapsed_ms: number
  boards: BoardReading[]
  errors: { slot: string; error: string }[]
  note?: string
}

/** One line of the history list; cheap enough to hold thousands of. */
export interface SnapshotSummary {
  id: string
  crate: string
  taken_at: string
  taken_at_local: string
  elapsed_ms: number
  boards: number
  channels: number
  powered: number
  faults: number
  errors: number
  note: string
}

export interface LiveChannel {
  slot: number
  channel: number
  name: string
}

export interface Crate {
  id: string
  label: string
  host: string
  system_type: string
  username: string
  note: string
  latest: SnapshotSummary | null
  /** Channels shown on the LILAK portal's live wall. */
  live_channels: LiveChannel[]
  /** Whether the wall shows this crate's on/trip/alarm counts. */
  live_summary: boolean
  /** Minutes between archived snapshots; 0 keeps none on a timer. */
  archive_interval_min: number
}

export interface Day {
  day: string
  count: number
}
