import { useCallback, useEffect, useMemo, useState } from "react"
import { Button, Checkbox, Group, Select, TextInput } from "@mantine/core"
import { notifications } from "@mantine/notifications"
import { Camera, Check, ClipboardCopy, Download, List } from "lucide-react"

import { BoardTable } from "@/components/board-table"
import { ColumnPicker } from "@/components/column-picker"
import { HistoryPanel } from "@/components/history-panel"
import { ApiError, api } from "@/lib/api"
import { copyText } from "@/lib/clipboard"
import { CORE_PARAMS, allParams } from "@/lib/columns"
import { diffSnapshots } from "@/lib/diff"
import type { RowFilter } from "@/lib/filter"
import { ago, stampTime } from "@/lib/format"
import { snapshotText } from "@/lib/report"
import type { Crate, Day, Snapshot, SnapshotSummary } from "@/lib/types"

const COLUMN_KEY = "hv.columns"

/** Remembered per browser: which columns this operator works with. */
function loadColumns(): string[] | null {
  try {
    const raw = window.localStorage.getItem(COLUMN_KEY)
    return raw ? (JSON.parse(raw) as string[]) : null
  } catch {
    // Private window, or storage turned off. The default set is fine.
    return null
  }
}

function saveColumns(chosen: Set<string>): void {
  try {
    window.localStorage.setItem(COLUMN_KEY, JSON.stringify([...chosen]))
  } catch {
    /* nothing to do: the choice just will not survive a reload */
  }
}

export default function App() {
  const [crates, setCrates] = useState<Crate[]>([])
  const [crateId, setCrateId] = useState<string | null>(null)

  const [current, setCurrent] = useState<Snapshot | null>(null)
  const [baseline, setBaseline] = useState<Snapshot | null>(null)
  /** null means "the snapshot taken just before this one", followed automatically. */
  const [pinnedBaseline, setPinnedBaseline] = useState<string | null>(null)

  const [history, setHistory] = useState<SnapshotSummary[]>([])
  const [days, setDays] = useState<Day[]>([])
  const [day, setDay] = useState<string | null>(null)

  const [chosen, setChosen] = useState<Set<string>>(() => new Set(loadColumns() ?? CORE_PARAMS))
  const [filter, setFilter] = useState<RowFilter>({
    text: "",
    changedOnly: false,
    poweredOnly: false,
    faultsOnly: false,
  })

  /** Channels on the portal's live wall, for the crate on screen. */
  const [livePicks, setLivePicks] = useState<{ slot: number; channel: number; name: string }[]>([])

  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  const fail = useCallback((err: unknown, what: string) => {
    const message = err instanceof ApiError ? err.message : String(err)
    setError(`${what}: ${message}`)
    notifications.show({ color: "red", title: what, message })
  }, [])

  // -- loading ------------------------------------------------------------

  useEffect(() => {
    api
      .crates()
      .then((found) => {
        setCrates(found)
        setCrateId((chosenId) => chosenId ?? found[0]?.id ?? null)
      })
      .catch((err) => fail(err, "Could not list the crates"))
  }, [fail])

  const refreshHistory = useCallback(
    async (id: string, forDay: string | null) => {
      const [entries, dayList] = await Promise.all([
        api.history(id, forDay ? { day: forDay } : {}),
        api.days(id),
      ])
      setHistory(entries)
      setDays(dayList)
      return entries
    },
    [],
  )

  /** The live picks on one board, as a set of channel numbers. */
  const liveOnBoard = useCallback(
    (slot: number) => new Set(livePicks.filter((pick) => pick.slot === slot).map((pick) => pick.channel)),
    [livePicks],
  )

  /** Put a channel on the portal's live wall, or take it off, and save.
   *  Config only: this never reads the crate. */
  const toggleLive = useCallback(
    (slot: number, channel: number) => {
      if (!crateId) return
      const on = livePicks.some((pick) => pick.slot === slot && pick.channel === channel)
      const next = on
        ? livePicks.filter((pick) => !(pick.slot === slot && pick.channel === channel))
        : [...livePicks, { slot, channel, name: "" }].sort((a, b) => a.slot - b.slot || a.channel - b.channel)
      setLivePicks(next)                                  // optimistic
      api
        .setLiveChannels(crateId, next)
        .then((saved) => {
          setLivePicks(saved.channels)
          setCrates((all) =>
            all.map((crate) => (crate.id === crateId ? { ...crate, live_channels: saved.channels } : crate)),
          )
        })
        .catch((err) => {
          setLivePicks(livePicks)                         // put it back
          fail(err, "Could not save the live channels")
        })
    },
    [crateId, livePicks],
  )

  // Switching crate resets everything that belongs to the old one, then opens
  // its most recent snapshot so the page is never blank when there is history.
  useEffect(() => {
    if (!crateId) return
    let cancelled = false
    setCurrent(null)
    setBaseline(null)
    setPinnedBaseline(null)
    setDay(null)
    setError(null)
    setLivePicks(crates.find((crate) => crate.id === crateId)?.live_channels ?? [])

    refreshHistory(crateId, null)
      .then(async (entries) => {
        if (cancelled || entries.length === 0) return
        const latest = await api.snapshot(crateId, entries[0].id)
        if (!cancelled) setCurrent(latest)
      })
      .catch((err) => {
        if (!cancelled) fail(err, "Could not read the archive")
      })

    return () => {
      cancelled = true
    }
  }, [crateId, refreshHistory, fail])

  // The day filter only changes which snapshots are listed, not which is open.
  useEffect(() => {
    if (!crateId) return
    let cancelled = false
    api
      .history(crateId, day ? { day } : {})
      .then((entries) => {
        if (!cancelled) setHistory(entries)
      })
      .catch((err) => {
        if (!cancelled) fail(err, "Could not list that day")
      })
    return () => {
      cancelled = true
    }
  }, [crateId, day, fail])

  /** Unless one is pinned, compare against whatever was taken just before. */
  const baselineId = useMemo(() => {
    if (pinnedBaseline) return pinnedBaseline
    if (!current) return null
    return history.find((entry) => entry.id < current.id)?.id ?? null
  }, [pinnedBaseline, current, history])

  useEffect(() => {
    if (!crateId || !baselineId) {
      setBaseline(null)
      return
    }
    if (baseline?.id === baselineId) return
    let cancelled = false
    api
      .snapshot(crateId, baselineId)
      .then((snapshot) => {
        if (!cancelled) setBaseline(snapshot)
      })
      .catch(() => {
        // A baseline that will not load is not worth an alert; the table just
        // shows no comparison.
        if (!cancelled) setBaseline(null)
      })
    return () => {
      cancelled = true
    }
  }, [crateId, baselineId, baseline?.id])

  // -- actions ------------------------------------------------------------

  const takeSnapshot = useCallback(async () => {
    if (!crateId || busy) return
    setBusy(true)
    setError(null)
    try {
      const snapshot = await api.takeSnapshot(crateId)
      setCurrent(snapshot)
      // Follow the live edge again: a new reading is compared with the one
      // before it, not with whatever was pinned an hour ago.
      setPinnedBaseline(null)
      setDay(null)
      await refreshHistory(crateId, null)
    } catch (err) {
      fail(err, "Snapshot failed")
    } finally {
      setBusy(false)
    }
  }, [crateId, busy, refreshHistory, fail])

  const openSnapshot = useCallback(
    async (id: string) => {
      if (!crateId) return
      try {
        setCurrent(await api.snapshot(crateId, id))
        setError(null)
      } catch (err) {
        fail(err, "Could not open that snapshot")
      }
    },
    [crateId, fail],
  )

  // R takes a snapshot, the way F5 would if F5 were free.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA"
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return
      if (event.key === "r" || event.key === "R") {
        event.preventDefault()
        void takeSnapshot()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [takeSnapshot])

  // -- derived ------------------------------------------------------------

  const params = useMemo(() => allParams(current), [current])
  const changes = useMemo(() => diffSnapshots(current, baseline), [current, baseline])

  // A column the current boards do not have would be an unticked box the
  // operator cannot explain, so the picker only offers what is on screen.
  const activeColumns = useMemo(
    () => new Set(params.filter((spec) => chosen.has(spec.name)).map((spec) => spec.name)),
    [params, chosen],
  )

  const totals = useMemo(() => {
    if (!current) return null
    return {
      channels: current.boards.reduce((sum, board) => sum + board.channels, 0),
      powered: current.boards.reduce((sum, board) => sum + board.powered, 0),
      faults: current.boards.reduce((sum, board) => sum + board.faults, 0),
    }
  }, [current])

  const setColumns = (next: Set<string>) => {
    setChosen(next)
    saveColumns(next)
  }

  /** The visible channels, as text, for the logbook. */
  const copyVisible = useCallback(async () => {
    if (!current) return
    const text = snapshotText(current, activeColumns, changes, filter)
    if (await copyText(text)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } else {
      notifications.show({ color: "red", message: "Could not reach the clipboard." })
    }
  }, [current, activeColumns, changes, filter])

  return (
    <div className="app">
      <div className="bar">
        <span className="bar-title">HV Monitoring</span>

        <Select
          aria-label="Crate"
          data={crates.map((crate) => ({ value: crate.id, label: `${crate.label} · ${crate.host}` }))}
          value={crateId}
          onChange={setCrateId}
          allowDeselect={false}
          disabled={crates.length === 0}
          comboboxProps={{ width: 280, position: "bottom-start" }}
          w={210}
        />

        <Button
          onClick={() => void takeSnapshot()}
          loading={busy}
          disabled={!crateId}
          leftSection={<Camera size={13} />}
          title="Read the crate now (R)"
        >
          Snapshot
        </Button>

        {current ? (
          <>
            <span className="tabular">{stampTime(current.taken_at_local)}</span>
            <span className="meta">{ago(current.taken_at)}</span>
            <span className="meta">{current.elapsed_ms} ms</span>
            {totals ? (
              <span className="meta">
                {current.boards.length} boards · {totals.channels} ch ·{" "}
                <b className={totals.powered > 0 ? "on" : "dim"}>{totals.powered} on</b>
                {totals.faults > 0 ? <b className="fault"> · {totals.faults} fault</b> : null}
              </span>
            ) : null}
          </>
        ) : (
          <span className="meta">no snapshot open</span>
        )}

        <span className="spacer" />

        {current ? (
          <Button
            variant="default"
            onClick={() => void copyVisible()}
            leftSection={copied ? <Check size={13} /> : <ClipboardCopy size={13} />}
            title="Copy the channels on screen as text"
          >
            {copied ? "Copied" : "Copy"}
          </Button>
        ) : null}

        {current && crateId ? (
          <Button
            component="a"
            href={api.csvUrl(crateId, current.id)}
            variant="default"
            leftSection={<Download size={13} />}
            title="Download this snapshot as CSV"
          >
            CSV
          </Button>
        ) : null}

        <Button
          variant="default"
          onClick={() => setHistoryOpen((open) => !open)}
          leftSection={<List size={13} />}
          hiddenFrom="sm"
        >
          History
        </Button>
      </div>

      <div className="bar">
        <TextInput
          aria-label="Filter channels"
          placeholder="filter by name or channel"
          value={filter.text}
          onChange={(event) => setFilter({ ...filter, text: event.currentTarget.value })}
          w={190}
        />

        <ColumnPicker params={params} chosen={activeColumns} onChange={setColumns} />

        <Group gap="md">
          <Checkbox
            size="xs"
            label="on only"
            checked={filter.poweredOnly}
            onChange={(event) => setFilter({ ...filter, poweredOnly: event.currentTarget.checked })}
          />
          <Checkbox
            size="xs"
            label="faults only"
            checked={filter.faultsOnly}
            onChange={(event) => setFilter({ ...filter, faultsOnly: event.currentTarget.checked })}
          />
          <Checkbox
            size="xs"
            label="changed only"
            checked={filter.changedOnly}
            disabled={!baseline}
            onChange={(event) => setFilter({ ...filter, changedOnly: event.currentTarget.checked })}
          />
        </Group>

        <span className="spacer" />

        {baseline ? (
          <>
            <span className="meta">
              vs {stampTime(baseline.taken_at_local)} · {changes.size} changed
              {pinnedBaseline ? " · pinned" : ""}
            </span>
            {pinnedBaseline ? (
              <Button variant="default" onClick={() => setPinnedBaseline(null)}>
                Unpin
              </Button>
            ) : null}
          </>
        ) : (
          <span className="meta">nothing to compare against yet</span>
        )}
      </div>

      {error ? <div className="notice">{error}</div> : null}

      <div className="body">
        <HistoryPanel
          entries={history}
          days={days}
          day={day}
          currentId={current?.id ?? null}
          baselineId={baseline?.id ?? null}
          open={historyOpen}
          onSelectDay={setDay}
          onOpen={(id) => {
            setHistoryOpen(false)
            void openSnapshot(id)
          }}
          onCompare={(id) => setPinnedBaseline(id === pinnedBaseline ? null : id)}
        />

        <main className="main">
          {current ? (
            <>
              {current.errors.map((entry) => (
                <div key={entry.slot} className="notice">
                  slot {entry.slot}: {entry.error}
                </div>
              ))}
              {current.boards.map((board) => (
                <BoardTable
                  key={board.slot}
                  board={board}
                  chosen={activeColumns}
                  changes={changes}
                  filter={filter}
                  live={liveOnBoard(board.slot)}
                  onLive={toggleLive}
                />
              ))}
            </>
          ) : (
            <div className="empty">
              {crateId
                ? "Press Snapshot to read the crate, or pick an earlier one from the list."
                : "No crates configured — see backend/data/crates.json."}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
