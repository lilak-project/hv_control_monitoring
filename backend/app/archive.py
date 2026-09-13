"""The timer that keeps a crate's history.

There was none. Snapshots appeared only as a side effect of something else
asking -- an operator pressing the button, or an elog fill coming through the
webhook -- and when the live wall was changed to read the crate without
archiving what it read, the last automatic source went with it. The archive
stopped dead on 2026-09-11 20:47 and nobody noticed for two days, because
nothing was broken: every endpoint answered, the wall showed live numbers, and
the only symptom was a gap in a record nobody looks at until they need it.

So the record now has its own clock. Per crate, `archive_interval_min`
(0 turns it off).

It is deliberately cheap. Every read of a CAEN crate is a LOGIN, and the GECO
window on the crate PC announces every one of them to whoever is sitting in
front of it -- which is why the live wall reads at most every ten minutes. So
this reuses whatever reading is already in hand when that reading is younger
than the interval, and only sweeps when there is nothing recent enough. At the
default the two line up and the crate sees one login per interval, not two.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from . import elog, snaplog
from .store import CrateConfig, load_crates

log = logging.getLogger("hv.archive")

#: How often the timer wakes to see whether anything is due. Far shorter than
#: any sensible interval, so a crate is archived close to when it should be,
#: and doing nothing costs nothing.
TICK_SEC = 20.0

_stop = threading.Event()
_thread: threading.Thread | None = None

#: crate id -> monotonic time of the last archive we know about. Seeded from
#: the archive itself on the first tick, so a restart does not write a snapshot
#: it does not owe.
_last: dict[str, float] = {}

#: crate id -> when we may try again after a failure, and whether the failure
#: has been logged. A crate that cannot be reached -- one registered but
#: powered down for the season, say -- was otherwise retried on every tick and
#: said so in the log every time: a warning every twenty seconds, for ever,
#: about a crate nobody expects to answer.
RETRY_SEC = 600.0
_retry_after: dict[str, float] = {}
_complained: set[str] = set()


def _seed(crate_id: str) -> float:
    """When this crate was last archived, as a monotonic instant.

    Read from the newest stored snapshot, so restarting the service keeps the
    cadence instead of restarting it. A crate with no history at all is treated
    as long overdue, which is what it is.
    """
    summary = snaplog.latest(crate_id)
    if not summary:
        return float("-inf")
    try:
        age = elog._age_of(snaplog.load(crate_id, summary["id"]))
    except (OSError, ValueError, KeyError):
        age = None
    if age is None:
        return float("-inf")
    return time.monotonic() - age


def _due(crate: CrateConfig) -> bool:
    if crate.archive_interval_min <= 0:
        return False
    if time.monotonic() < _retry_after.get(crate.id, 0.0):
        return False
    if crate.id not in _last:
        _last[crate.id] = _seed(crate.id)
    return (time.monotonic() - _last[crate.id]) >= crate.archive_interval_min * 60.0


def _archive_one(crate: CrateConfig) -> None:
    """Keep one reading for one crate, reusing a recent one where there is one."""
    # A reading younger than the interval is as good as a new one and costs no
    # login. Older than that and `_reading` sweeps the crate itself.
    reading, age, source = elog._reading(crate, max_age=crate.archive_interval_min * 60.0)
    if reading is None:
        # Back off, and say so once. Retrying every tick would neither reach the
        # crate nor stop filling the log, and the next interval is soon enough
        # for a crate that has nothing to say.
        _retry_after[crate.id] = time.monotonic() + min(RETRY_SEC, crate.archive_interval_min * 60.0)
        if crate.id not in _complained:
            _complained.add(crate.id)
            log.warning("%s: cannot be read (%s); retrying every %.0f min, quietly",
                        crate.id, source, min(RETRY_SEC, crate.archive_interval_min * 60.0) / 60.0)
        return
    if crate.id in _complained:
        _complained.discard(crate.id)
        log.info("%s: readable again", crate.id)
    _retry_after.pop(crate.id, None)
    if reading.get("id"):
        # It came out of the archive -- it is already kept, and writing it again
        # would file an old reading under a new time.
        _last[crate.id] = time.monotonic() - (age or 0.0)
        return
    try:
        saved = snaplog.save(reading)
    except Exception as err:                  # pragma: no cover - disk trouble
        log.error("%s: could not archive: %s", crate.id, err)
        return
    _last[crate.id] = time.monotonic() - (age or 0.0)
    log.info("%s: archived %s (%s, %.0fs old)", crate.id, saved.get("id"), source, age or 0.0)


def _loop() -> None:
    while not _stop.is_set():
        try:
            for crate in load_crates():
                if _stop.is_set():
                    break
                if _due(crate):
                    _archive_one(crate)
        except Exception:                     # pragma: no cover - never die here
            log.exception("archive tick failed")
        _stop.wait(TICK_SEC)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="hv-archive", daemon=True)
    _thread.start()
    wanted = [(c.id, c.archive_interval_min) for c in load_crates() if c.archive_interval_min > 0]
    if wanted:
        log.info("archiving on a timer: %s",
                 ", ".join(f"{cid} every {mins:g} min" for cid, mins in wanted))
    else:
        log.info("no crate has an archive interval; nothing is kept on a timer")


def stop() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=3)


def status() -> list[dict[str, Any]]:
    """What the timer is doing, for the settings page."""
    out = []
    for crate in load_crates():
        last = _last.get(crate.id)
        since = None if last in (None, float("-inf")) else time.monotonic() - last
        out.append({
            "crate": crate.id,
            "interval_min": crate.archive_interval_min,
            "seconds_since_last": since,
            "next_in_seconds": (None if crate.archive_interval_min <= 0 or since is None
                                else max(0.0, crate.archive_interval_min * 60.0 - since)),
        })
    return out
