"""The LILAK elog endpoint: one POST that answers both of elog's questions.

elog talks to a service through a single URL. Two different bodies arrive on it:

    {"event": "elog_handshake", "elog_url": …}
        -> who we are and what fields we can fill (Discover, once, at registration)

    {"format_id", "format_name", "task_log_id", "run_number", "requested_at", "mode"}
        -> the values themselves (every fill, on a task or on a schedule)

Two rules shape everything below.

**Five seconds.** elog gives up after that (`WEBHOOK_TIMEOUT_SEC`) and turns the
task into a manual one with the error as a comment. `mode` may also be
"realtime", which repeats as often as twice a second. So a reader here must be
cheap and must never block on hardware it does not already hold.

**The field list is fixed.** elog builds a log format from `log_fields` at
registration and matches it later by name *and* field signature: declare a
different set and a second format appears rather than the first one changing.
So `log_fields` must come from configuration, never from what is currently
plugged in, connected or selected -- otherwise unplugging a cable forks the
format and last week's entries stop lining up with this week's.

Copied into each service rather than shared from one place: these services are
each movable as a single folder (SERVICE_CONTRACT §9), and a shared import
would tie them together at runtime for eighty lines.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("elog")

HANDSHAKE = "elog_handshake"

#: A field elog can put on a log format.
#: `type` is one of number_entry | number | text | body | title | tags | level.
#: `metric` (number types only) makes it an Infography variable.
Field = dict[str, Any]


def number(key: str, label: str, unit: str = "", metric: bool = True) -> Field:
    """A numeric field. number_entry is the shape elog normalises to {value,error}."""
    return {"key": key, "label": label, "type": "number_entry", "unit": unit, "metric": metric}


def text(key: str, label: str) -> Field:
    return {"key": key, "label": label, "type": "text"}


def body(label: str = "Summary") -> Field:
    return {"key": "body", "label": label, "type": "body"}


def value(number_value: float | None, error: float = 0.0) -> dict:
    """One number_entry value. None stays None -- a channel that reported
    nothing is not the same as one that reported zero."""
    return {"value": None if number_value is None else float(number_value), "error": error}


def make_router(
    *,
    service_name: str,
    description: str,
    log_fields: list[Field] | Callable[[], Awaitable[list[Field]]],
    read: Callable[[dict], Awaitable[dict]],
    directory: str = "",
    path: str = "/api/elog",
) -> APIRouter:
    """The endpoint. `read(envelope)` returns the `fields` dict for one request.

    `log_fields` is normally a plain list -- a constant, which is what the
    "fixed field list" rule above asks for. It may instead be an async callable
    for a service whose fields come from its own saved configuration (which
    actuators are set up, say). That is still configuration and still stable;
    it just cannot be written down at import time. Such a callable should RAISE
    rather than return a short list when it cannot read that configuration, so
    Discover fails loudly instead of quietly registering half a format.

    Mount this BEFORE any catch-all `/api/{path}` route: FastAPI matches in
    registration order, and the read-only mirrors answer 405 to every POST they
    do not recognise -- including this one.
    """
    router = APIRouter(tags=["elog"])

    @router.post(path, summary="LILAK elog handshake and data request")
    async def elog_endpoint(request: Request):
        try:
            envelope = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "body must be JSON"})
        if not isinstance(envelope, dict):
            return JSONResponse(status_code=400, content={"detail": "body must be a JSON object"})

        event = envelope.get("event")
        if event == HANDSHAKE:
            log.info("elog handshake from %s", envelope.get("elog_url") or "?")
            try:
                fields = log_fields if isinstance(log_fields, list) else await log_fields()
            except Exception as err:
                log.warning("handshake refused: %s", err)
                return JSONResponse(status_code=503, content={"detail": str(err)})
            return {
                "name": service_name,
                "description": description,
                "hostname": socket.gethostname(),
                "directory": directory,
                # A service, not a system: elog asks us, we never push runs at it.
                "is_system": False,
                "log_fields": fields,
            }
        if event:
            # Only the handshake is an event. Anything else is a system-only
            # message (elog_credentials) or a typo, and answering it with
            # readings would be worse than saying so.
            return JSONResponse(
                status_code=400,
                content={"detail": f"unknown event {event!r}; this is a plain service, not a system"},
            )

        fields = await read(envelope)
        return {"fields": fields}

    return router


# ── This service's answer ────────────────────────────────────────────────────

import os                                                          # noqa: E402
import threading                                                   # noqa: E402
import time                                                        # noqa: E402
from datetime import datetime, timezone                            # noqa: E402

from fastapi.concurrency import run_in_threadpool                  # noqa: E402

from . import snaplog, snapshot                                    # noqa: E402
from .caen import CaenError                                        # noqa: E402
from .config import SNAPSHOT_ROOT                                  # noqa: E402
from .store import load_crates                                     # noqa: E402

#: How stale a reading may be before this endpoint goes and takes a new one.
#:
#: The crate is not polled by this service -- a reading is a login, a sweep and
#: a logout -- so without a floor, elog's realtime mode (as often as twice a
#: second) would hold the CAEN library permanently and lock out the operator
#: pressing Snapshot. Thirty seconds is well inside what an HV log entry needs
#: and far outside what would get in anyone's way.
MAX_AGE_SEC = float(os.environ.get("HV_ELOG_MAX_AGE", "30"))

#: How long to wait for the CAEN library before giving up and answering from
#: the last reading. elog's whole round trip has five seconds.
BUSY_WAIT_SEC = float(os.environ.get("HV_ELOG_BUSY_WAIT", "1.5"))

#: The two alarm thresholds, as percentages. Configuration, not live state --
#: they are part of what the numbers MEAN, so they are also written into the
#: body of every entry rather than left implicit.
ALARM_V_PCT = float(os.environ.get("HV_ALARM_V_PCT", "5"))
ALARM_I_PCT = float(os.environ.get("HV_ALARM_I_PCT", "50"))

#: Never archive more often than this from a webhook fill. The archive is the
#: record of readings somebody chose to keep; a scheduled fill every minute is
#: welcome in it, elog's realtime mode (twice a second) would bury everything
#: else within an hour.
SNAPSHOT_MIN_INTERVAL = float(os.environ.get("HV_ELOG_SNAPSHOT_MIN_INTERVAL", "60"))

#: How stale a cached reading may be before the live wall asks the crate again.
#:
#: Ten minutes, not seconds: every read is a LOGIN, and the CAEN GECO window on
#: the crate PC announces "Someone has connected to …" for each one. A wall that
#: swept every few seconds turned that into a permanent banner in front of the
#: operator. At ten minutes the wall adds nothing beyond the elog fills, which
#: log in on their own schedule anyway, and the tile says how old its numbers
#: are. Lower it (HV_LIVE_MAX_AGE, seconds) if a fresher wall is worth the
#: banner; raise it further and the wall simply shows the last reading anyone
#: took.
LIVE_MAX_AGE_SEC = float(os.environ.get("HV_LIVE_MAX_AGE", "600"))

#: After a failed login the live wall stops trying for this long. A crate that
#: is off or on an unrouted subnet fails slowly -- a login timeout every poll
#: would make the whole wall wait on it -- and the tile says how old its
#: numbers are either way.
LIVE_RETRY_SEC = float(os.environ.get("HV_LIVE_RETRY", "300"))
_live_failed: dict[str, float] = {}

#: Alarm lines listed in the body before it starts saying "and N more".
BODY_ROWS = int(os.environ.get("HV_ELOG_BODY_ROWS", "15"))

#: Fixed, whatever cards are in the crate.
#:
#: Fifty-six channels times name/VMon/IMon/on-off would be over a hundred and
#: fifty fields, and swapping a card would change the list and fork the format.
#: What a logbook wants at a glance is four numbers -- how much is on, how much
#: tripped, and the two alarm counts -- so those are the numbers, the per-channel
#: detail goes to a snapshot FILE whose path is in the entry, and the body holds
#: only the channels that are actually saying something.
#:
#: Labels are static on purpose even though the thresholds are configurable:
#: elog matches a format by its field signature, so a label that moved with a
#: setting would fork the format the first time somebody tuned it.
LOG_FIELDS = [
    number("channels_on", "Channels on", "ch"),
    number("trips", "Tripped", "ch"),
    number("alarm_v", "V alarm", "ch"),
    number("alarm_i", "I alarm", "ch"),
    number("channels_total", "Channels total", "ch"),
    number("reading_age_s", "Age of this reading", "s", metric=False),
    text("crate", "Crate"),
    text("taken_at", "Reading taken at"),
    text("snapshot", "Snapshot file"),
    body("Alarms"),
]

_lock = threading.Lock()
#: crate id -> (monotonic seconds when taken, the reading)
_cache: dict[str, tuple[float, dict]] = {}
#: crate id -> (monotonic seconds when archived, the path written)
_archived: dict[str, tuple[float, str]] = {}


def _cached(crate_id: str) -> tuple[float, dict] | None:
    with _lock:
        return _cache.get(crate_id)


def _remember(crate_id: str, reading: dict) -> None:
    with _lock:
        _cache[crate_id] = (time.monotonic(), reading)


def _reading(crate, max_age: float = MAX_AGE_SEC, skip_sweep: bool = False) -> tuple[dict | None, float | None, str]:
    """The crate's state: the reading, how old it is in seconds, and where it came from.

    Three sources, in order of preference -- a fresh sweep, the last one this
    endpoint took, and the newest archived snapshot. The archive matters: a
    service that has just restarted has no cache, and an hour-old reading
    labelled as an hour old is far better for a logbook than a blank.
    """
    held = _cached(crate.id)
    if held is not None and time.monotonic() - held[0] < max_age:
        return held[1], time.monotonic() - held[0], "live"

    if not skip_sweep:
        try:
            fresh = snapshot.take(crate, busy_timeout=BUSY_WAIT_SEC)
        except CaenError as err:
            log.info("%s: %s; answering from the last reading", crate.id, err)
            _live_failed[crate.id] = time.monotonic()
        else:
            _live_failed.pop(crate.id, None)
            _remember(crate.id, fresh)
            return fresh, 0.0, "live"

    if held is not None:
        return held[1], time.monotonic() - held[0], "cached"

    summary = snaplog.latest(crate.id)
    if summary is not None:
        try:
            stored = snaplog.load(crate.id, summary["id"])
        except (OSError, ValueError, KeyError):
            return None, None, "unreachable"
        return stored, _age_of(stored), "archive"

    return None, None, "unreachable"


def _age_of(reading: dict) -> float | None:
    """Seconds since a reading's own timestamp, for one loaded from the archive."""
    try:
        taken = datetime.fromisoformat(str(reading["taken_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - taken).total_seconds())


def _unit(board: dict, param: str) -> str:
    """The unit THIS board reports a parameter in.

    Not a constant: on the same crate an A1542HSN reports IMon in µA and an
    A2551A low-voltage card reports it in A. A hardcoded "uA" would write 1.35 A
    into a logbook as 1.35 µA, and nothing downstream could tell.
    """
    for spec in board.get("params", []):
        if spec.get("name") == param:
            return spec.get("unit") or ""
    return ""


def _fmt(number_value) -> str:
    if number_value is None:
        return "—"
    try:
        return f"{float(number_value):,.2f}"
    except (TypeError, ValueError):
        return str(number_value)


def _pct_off(monitor, setting) -> float | None:
    """How far a monitored value sits from its setting, as a percent of the setting.

    None when there is nothing to compare against: a setting of zero has no
    percentage, and a channel that reported no value is not a channel reading
    zero.
    """
    try:
        setting = float(setting)
        monitor = float(monitor)
    except (TypeError, ValueError):
        return None
    if setting == 0:
        return None
    return abs(monitor - setting) / abs(setting) * 100.0


def _metrics(reading: dict) -> tuple[dict[str, int], list[str]]:
    """The four numbers, and one line for each channel that earned a mention.

    Both alarms are counted over POWERED, SETTLED channels only, and that is not
    a detail. A channel that is off reads VMon 0 against a V0Set of 112, which is
    100 % away from its setting -- include those and the V alarm reads "every
    channel that is not on", which is noise wearing an alarm's name. A channel
    on its way up or down is legitimately far from its setting for as long as
    the ramp lasts, so ramping channels are skipped too.
    """
    counts = {"total": 0, "on": 0, "trips": 0, "alarm_v": 0, "alarm_i": 0}
    lines: list[str] = []

    for board in reading.get("boards", []):
        volt_unit = _unit(board, "VMon")
        current_unit = _unit(board, "IMon")
        for row in board.get("rows", []):
            counts["total"] += 1
            values = row.get("values", {})
            flags = (row.get("status") or {}).get("flags") or []
            powered = values.get("Pw") == 1
            if powered:
                counts["on"] += 1

            where = f"{board['slot']:>2}.{row['channel']:<3} {row.get('name') or '':<20}"

            # A trip is counted wherever it is found: a tripped channel has
            # usually switched itself off, so gating this on `powered` would
            # hide exactly the ones worth reporting.
            tripped = "Internal trip" in flags or "External trip" in flags
            if tripped:
                counts["trips"] += 1
                lines.append(f"{where} TRIP  {', '.join(flags)}")
                continue

            ramping = "Ramp up" in flags or "Ramp down" in flags
            if not powered or ramping:
                continue

            v_off = _pct_off(values.get("VMon"), values.get("V0Set"))
            if v_off is not None and v_off >= ALARM_V_PCT:
                counts["alarm_v"] += 1
                lines.append(f"{where} V     {_fmt(values.get('VMon'))} {volt_unit} "
                             f"vs set {_fmt(values.get('V0Set'))} {volt_unit} "
                             f"({v_off:.1f} % off)")

            i_off = _pct_off(values.get("IMon"), values.get("I0Set"))
            if i_off is not None and i_off <= ALARM_I_PCT:
                counts["alarm_i"] += 1
                lines.append(f"{where} I     {_fmt(values.get('IMon'))} {current_unit} "
                             f"of limit {_fmt(values.get('I0Set'))} {current_unit} "
                             f"({i_off:.1f} % below)")

    return counts, lines


def live_reading(crate) -> tuple[dict | None, float | None, str]:
    """The crate's state for the portal's LIVE wall: the reading, its age, and
    where it came from.

    The same cache the elog fills use -- so a live poll and an elog task never
    read the crate twice within MAX_AGE_SEC -- and it NEVER archives. The wall
    is a window on the crate, not a reason to keep a file: snapshots are for
    elog fills and for the operator pressing Snapshot.
    """
    failed_at = _live_failed.get(crate.id)
    backing_off = failed_at is not None and time.monotonic() - failed_at < LIVE_RETRY_SEC
    return _reading(crate, max_age=LIVE_MAX_AGE_SEC, skip_sweep=backing_off)


def _archive(reading: dict, crate_id: str, mode: str) -> str:
    """Keep this reading, and say where it went. Returns "" when nothing was kept.

    A reading loaded from the archive already has an id and is not written
    again. Realtime fills never write -- see SNAPSHOT_MIN_INTERVAL.
    """
    existing = reading.get("id")
    if existing:
        try:
            return str(snaplog.path_of(crate_id, str(existing)))
        except Exception:                     # pragma: no cover - bad id in a file
            return ""

    with _lock:
        last = _archived.get(crate_id)
    if mode == "realtime":
        return last[1] if last else ""
    if last is not None and time.monotonic() - last[0] < SNAPSHOT_MIN_INTERVAL:
        return last[1]

    try:
        # No note: the archive list shows the time, and "elog task" told an
        # operator nothing they could act on. A note is for what a PERSON wants
        # to say about a reading.
        saved = snaplog.save(reading)
        written = str(snaplog.path_of(crate_id, saved["id"]))
    except Exception as err:
        # Failing to archive must not fail the reply: the numbers are still
        # true, they just cannot be looked up later.
        log.warning("could not archive the reading for %s: %s", crate_id, err)
        return last[1] if last else ""

    with _lock:
        _archived[crate_id] = (time.monotonic(), written)
    return written


def _blank(crate_label: str, why: str) -> dict:
    return {
        "channels_on": value(None), "trips": value(None),
        "alarm_v": value(None), "alarm_i": value(None),
        "channels_total": value(None), "reading_age_s": value(None),
        "crate": crate_label, "taken_at": "", "snapshot": "",
        "body": why,
    }


async def read(envelope: dict) -> dict:
    """Four numbers, a file path, and only the channels that are saying something.

    One crate, not all of them: a log format has one set of fields, and a
    second crate's channels would have nowhere to go. Which crate is the first
    in crates.json -- and its name is in the log, so a two-crate bench can tell.
    """
    crates = await run_in_threadpool(load_crates)
    if not crates:
        return _blank("", "No crate is configured in this service.")

    crate = crates[0]
    mode = str(envelope.get("mode") or "task")
    # A crate read is a blocking C call; off the event loop it goes.
    reading, age, source = await run_in_threadpool(_reading, crate)

    if reading is None:
        return _blank(crate.label or crate.id,
                      f"{crate.label or crate.id} ({crate.host}) could not be read and "
                      "there is no earlier reading to fall back on.")

    counts, alarms = _metrics(reading)
    written = await run_in_threadpool(_archive, reading, crate.id, mode)

    head = [f"{counts['on']} of {counts['total']} channels on · "
            f"{counts['trips']} tripped · "
            f"{counts['alarm_v']} V alarm (≥{ALARM_V_PCT:g} % off set) · "
            f"{counts['alarm_i']} I alarm (within {ALARM_I_PCT:g} % of limit)"]
    if alarms:
        head.append("")
        head.extend(alarms[:BODY_ROWS])
        if len(alarms) > BODY_ROWS:
            head.append(f"… and {len(alarms) - BODY_ROWS} more")
    else:
        head.append("Nothing tripped and nothing in alarm.")
    if written:
        head += ["", f"snapshot: {written}"]
    if source != "live":
        note = ("from this service's last reading" if source == "cached"
                else "from the newest archived snapshot")
        head.append(f"⚠ the crate did not answer just now; the above is {note}"
                    + (f", {age:,.0f} s old" if age is not None else ""))

    return {
        "channels_on": value(counts["on"]),
        "trips": value(counts["trips"]),
        "alarm_v": value(counts["alarm_v"]),
        "alarm_i": value(counts["alarm_i"]),
        "channels_total": value(counts["total"]),
        "reading_age_s": value(None if age is None else round(age, 1)),
        "crate": crate.label or crate.id,
        "taken_at": reading.get("taken_at", ""),
        "snapshot": written,
        # Fenced, like actuator_monitoring's: elog renders a body as Markdown,
        # which folds runs of spaces and single newlines into one space, so the
        # aligned rows above arrive as one long line without it.
        "body": "```\n" + "\n".join(head) + "\n```",
    }


router = make_router(
    service_name="HV Monitoring",
    description=("CAEN crate readout, compressed: channels on, tripped, and two alarm "
                 "counts (VMon off its set point, IMon near its current limit). The "
                 "full per-channel reading is archived as a snapshot file and the "
                 "entry names it."),
    log_fields=LOG_FIELDS,
    read=read,
    directory=str(SNAPSHOT_ROOT),
)
