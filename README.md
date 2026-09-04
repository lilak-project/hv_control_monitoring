# HV Monitoring

On-demand readout of the CAEN HV crates. Press **Snapshot**, and the service
logs into the crate, reads every parameter of every channel on every populated
board, logs out, and shows it as one dense table. Every snapshot is kept, filed
under the day it was taken, and any two can be compared.

There is no polling loop. The crate is read when someone asks, which is what
makes a full sweep affordable: the whole crate comes back in about 150 ms.

Read-only. The write side of the CAEN API is deliberately not bound — see
[Safety](#safety).

## Quick start

```bash
cd backend
pip install -r requirements.txt
python run.py                 # http://<this-host>:8003
```

The server prints every address it can be reached on, because this host sits on
the instrument subnet, the lab LAN and a VPN at once.

The UI is served from the same port, from `frontend/dist`. To rebuild it:

```bash
cd frontend
npm install
npm run build
```

For frontend work, `npm run dev` serves on port 5173 and proxies `/api` to
127.0.0.1:8003, so run the backend alongside it.

## What a snapshot contains

Everything the boards report about themselves, not a fixed list. An A1542HSN
gives seventeen parameters per channel:

```
V0Set I0Set V1Set I1Set RUp RDWn Trip SVMax VMon IMon
Status Pw POn PDwn ImRange TripInt TripExt
```

and the A2551A low-voltage card in slot 5 gives a different eighteen, including
`Temp`, `Intck`, `OVVThr` and `VCon`. The service asks each board what its
channels have, what type and unit each parameter is, and what range it covers,
then reads them all. Channel names come from the crate too — the `Q3`, `L_w1`,
`R_w1` an operator typed in.

## The UI

Deliberately plain: a 12 px table, two header rows, no cards and no elevation.
Fifty-six channels against eighteen parameters is a lot of numbers, and the
only thing that helps is fitting more of them on screen.

| | |
|---|---|
| **Snapshot** | Read the crate now. `R` does the same from the keyboard. |
| **Columns** | Opens on the six you check walking past the rack (`VMon IMon V0Set I0Set Pw Status`); every parameter is one click away. The choice is remembered per browser. |
| **Filters** | By channel name or number, and *on only* / *faults only* / *changed only*. |
| **History** | Every snapshot ever taken, newest first, grouped by day. Click to open one; the **Δ** button pins it as the thing everything is compared against. |
| **Comparison** | Unless one is pinned, a snapshot is compared with the one taken just before it. Cells that moved get an amber background, and the old reading on the tooltip. |
| **Copy** | The channels on screen — the filtered rows, the chosen columns, the same rounding — as fixed-width text, for the logbook or a chat window. |
| **CSV** | The open snapshot, one row per channel, for a spreadsheet. |

Colour carries one meaning each and nothing else is tinted: **green** is
powered, **red** is a fault bit in the status word, **amber** is a value that
moved since the comparison snapshot.

Channel numbers and names stay put when the parameter columns scroll sideways,
and the column headings stay put when the rows scroll down.

## The archive

One JSON file per snapshot, filed by crate and local calendar day:

```
backend/log/snapshots/stark/2026-08-29/20260829T204311.json
```

Local rather than UTC, because "show me yesterday afternoon" is a question
about the operator's day. The file still carries an unambiguous UTC timestamp
alongside the local one.

The file is written to be read by a person: indented throughout, but with each
channel on one line, so `grep` and a text editor are useful on it.

```json
      "rows": [
        {"channel": 0, "name": "Q3", "values": {"VMon": 0.0, "IMon": 0.0, "V0Set": 112.0, ...
        {"channel": 1, "name": "Q1", "values": {"VMon": 0.0, "IMon": 0.0, "V0Set": 112.0, ...
```

Indenting a channel fully would spread seventeen readings over twenty lines;
leaving the whole snapshot on one line makes no line tool any use. A 56-channel
snapshot is 166 lines and about 27 kB.

Each day directory also holds an `index.jsonl` — one summary line per snapshot,
appended as it is written — so listing a day never opens the snapshots
themselves. It is a cache, not the record: delete it and it rebuilds from the
files on the next listing.

Nothing is pruned automatically. A snapshot of this crate — three boards, 56
channels — is about 27 kB, so one a minute for a week is roughly 270 MB. Taken
by hand that is nothing; if you ever drive `POST /snapshot` from a timer,
prune the archive on a timer too.

## Configuration

Crates live in `backend/data/crates.json`:

```json
{
  "crates": [
    { "id": "stark", "label": "STARK", "host": "192.168.1.1",
      "system_type": "SY5527", "username": "admin", "password": "admin" }
  ]
}
```

`id` is what appears in URLs. `system_type` is a `CAENHV_SYSTEM_TYPE_t` name —
`SY5527`, `SY4527`, `SY1527`, `N1470` and so on.

Environment overrides, all optional:

| Variable | Default | |
|---|---|---|
| `HV_DATA_DIR` | `backend/data` | where `crates.json` is |
| `HV_LOG_DIR` | `backend/log` | root of the archive |
| `HV_STATIC_DIR` | `frontend/dist` | the built UI |
| `HV_BUSY_TIMEOUT` | `30` | seconds a request waits for the crate to be free |

## API

Browsable at `/docs`.

| | |
|---|---|
| `GET /api/health` | Is the CAEN library loaded, which crates are configured |
| `GET /api/crates` | The crates, each with its most recent snapshot |
| `POST /api/crates/{crate}/snapshot` | Read the crate now and archive it |
| `GET /api/crates/{crate}/snapshots` | History, newest first (`?day=`, `?limit=`, `?before=`) |
| `GET /api/crates/{crate}/snapshots/days` | Days that have snapshots, with counts |
| `GET /api/crates/{crate}/snapshots/{id}` | One archived snapshot |
| `GET /api/crates/{crate}/snapshots/{id}/csv` | The same, as CSV |
| `DELETE /api/crates/{crate}/snapshots/{id}` | Remove one snapshot |

An unreachable crate is a `502` with the reason, not a `500`. A crate that is
already being read and does not come free within `HV_BUSY_TIMEOUT` is a `409`.

## Safety

`backend/app/caen.py` binds the reading half of the CAEN HV Wrapper API and
nothing else. `CAENHV_SetChParam`, `CAENHV_SetChName`, `CAENHV_ExecComm` and
`CAENHV_SetBdParam` are not declared, so no bug in this service can move a
beamline voltage or switch a channel. To set a voltage, use `hvctl.py` in
`~/caenhv`, which asks for `--yes` before it writes.

## Notes

- **Why not `caen_hv_py`.** The `~/caenhv` scripts use that wrapper, which
  exposes three values per channel through a small shim `.so`, and whose
  `get_crate_map` reads the model strings at the wrong offsets. The library
  underneath it — `libcaenhvwrapper.so`, declared in
  `/usr/include/CAENHVWrapper.h` — reports every parameter, the channel names
  and a crate map that parses correctly. This service talks to that directly.
- **Thread safety.** The CAEN library keeps per-handle state in process
  globals, so all crate access is serialised behind one process-wide lock, and
  a snapshot runs in a worker thread rather than on the event loop.
- **Session lifetime.** The crate drops a session idle for about fifteen
  seconds, so there is no connection to keep alive between requests. Every
  snapshot is its own login.
- **Status bits.** The names beside a status word — *Ramp up*, *Over current*,
  *Internal trip* — are the HV boards' bit map. A low-voltage card such as the
  A2551A numbers its status word differently, so the raw hex word is always on
  the cell's tooltip.
- **Reachability.** `stark` (192.168.1.1) answers from this host on `eno3`.
  `asgard` (192.168.7.1) is configured but this host has no route to
  192.168.7.0/24, so snapshots of it fail after about five seconds with
  *login failed*. Add the route or the interface and it will work unchanged.
- **Passwords** sit in `crates.json` in plain text, as they do in the existing
  `~/caenhv` scripts. The file is not served to the browser — `/api/crates`
  returns everything about a crate except its password.

## Layout

```
backend/
  run.py                 start the server
  data/crates.json       which crates exist
  app/
    caen.py              ctypes binding for libcaenhvwrapper (read-only)
    snapshot.py          one pass over a crate
    snaplog.py           the archive: save, list, load, CSV
    store.py             crates.json
    config.py            paths and tunables
    net.py               which URLs this server can be opened on
    main.py              FastAPI app, serves the built UI
    routers/             crates.py, snapshots.py
frontend/
  src/
    App.tsx              toolbar, state, wiring
    theme.ts             the compact theme, and why it is compact
    index.css            the table
    components/          board-table, history-panel, column-picker
    lib/                 api, types, format, columns, diff, filter, report, clipboard
```

## In the LILAK elog

This service answers the elog's service contract on **`POST /api/elog`** — the
same URL handles both the handshake (Discover) and every later data request.
`app/elog.py` holds it, with the field list at the top.

Register it once, in the elog's Experiment tab → New Service, with this URL:

```
portal://hv/api/elog
```

`portal://` rather than a host and port: a portal-managed service's port is
picked from a pool when it starts and can differ after a restart, so a literal
`http://127.0.0.1:<port>` goes stale. elog resolves the scheme per call from
`$PORTAL_DATA_ROOT/hv/.port` (`lilak_elog/backend/portal_peer.py`). Running
this service standalone instead, register its real address.

Press **Discover**: elog reads the field list back and builds a `"HV Monitoring log"`
format from it. What it fills:

| | |
|---|---|
| `channels_on`, `channels_total`, `faults` | the counts, as Infography metrics |
| `reading_age_s` | how old the reading is — see the caching note below |
| `crate`, `taken_at` | which crate, and when it was read |
| `body` | every channel: slot, name, VMon, IMon, on/off, and any fault |

The crate has 56 channels. Declaring name/VMon/IMon/on-off per channel would be
over 150 fields and would change every time a card is swapped, so the numbers
worth plotting are numbers and the per-channel detail is a table in the body.

**IMon's unit is read per board, never assumed.** On this crate an A1542HSN
reports µA and an A2551A reports A; a hardcoded unit would write 1.35 A into a
logbook as 1.35 µA.

**The reading is cached and never archived.** A reading is a login, a sweep and
a logout, and this service has no polling loop — so `mode: "realtime"` would
otherwise hold the CAEN library permanently and lock out the operator pressing
Snapshot. A reading younger than `HV_ELOG_MAX_AGE` (30 s) is reused; otherwise
one is taken with a short `HV_ELOG_BUSY_WAIT` (1.5 s) rather than the 30 s the
Snapshot button waits. If the crate cannot be reached the answer falls back to
the last reading, then to the newest archived snapshot, and the body says so
with the age. Nothing this endpoint reads enters the archive: that file is the
record of snapshots somebody chose to take.

Two things about the field list. It is deliberately **fixed** — elog matches a
format by its field signature, so a list that changed with the hardware would
fork the format and last month's entries would stop lining up with this
month's. And elog gives up after **5 seconds**, with `mode: "realtime"`
repeating as often as twice a second, so the endpoint only ever reads state
this service already holds.
