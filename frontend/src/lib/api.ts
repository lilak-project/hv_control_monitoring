import type { Crate, Day, LiveChannel, Snapshot, SnapshotSummary } from "./types"

import { url } from "@/lib/portal-base"

/** The message the server sent, not "Failed to fetch". */
export class ApiError extends Error {
  /** HTTP status, or 0 when the request never reached the server. */
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url(path), init)
  } catch {
    // Offline, or the server went away mid-request. Status 0 means "never got there".
    throw new ApiError("cannot reach the server", 0)
  }
  if (!response.ok) {
    // FastAPI puts the reason in `detail`; fall back to the status line.
    const body = await response.json().catch(() => null)
    const detail =
      body && typeof body.detail === "string" ? body.detail : `${response.status} ${response.statusText}`
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  crates: () => request<Crate[]>("/api/crates"),

  /** Read the crate now.  Slow by web standards -- it is a round trip to hardware. */
  takeSnapshot: (crate: string, note = "") =>
    request<Snapshot>(`/api/crates/${crate}/snapshot?note=${encodeURIComponent(note)}`, {
      method: "POST",
    }),

  history: (crate: string, options: { day?: string; limit?: number } = {}) => {
    const query = new URLSearchParams()
    if (options.day) query.set("day", options.day)
    if (options.limit) query.set("limit", String(options.limit))
    const suffix = query.toString() ? `?${query}` : ""
    return request<SnapshotSummary[]>(`/api/crates/${crate}/snapshots${suffix}`)
  },

  days: (crate: string) => request<Day[]>(`/api/crates/${crate}/snapshots/days`),

  snapshot: (crate: string, id: string) => request<Snapshot>(`/api/crates/${crate}/snapshots/${id}`),

  remove: (crate: string, id: string) =>
    request<void>(`/api/crates/${crate}/snapshots/${id}`, { method: "DELETE" }),

  /** What this crate shows on the LILAK portal's live wall: the channel picks,
   *  and whether its on/trip/alarm counts appear. Either may be omitted to
   *  leave it alone. Config only -- saving this never touches the crate. */
  setLive: (crate: string, body: { channels?: LiveChannel[]; summary?: boolean }) =>
    request<{ crate: string; channels: LiveChannel[]; summary: boolean }>(
      `/api/crates/${crate}/live-channels`,
      { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) },
    ),

  // Used as an <a href>, not fetched -- so it carries the prefix itself.
  csvUrl: (crate: string, id: string) => url(`/api/crates/${crate}/snapshots/${id}/csv`),
}
