"""The list of crates this service can reach, read from ``data/crates.json``."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from .config import CRATE_FILE

_lock = threading.Lock()
_cache: list[CrateConfig] | None = None


#: Minutes between archived snapshots when a crate entry does not say.
DEFAULT_ARCHIVE_MIN = 10.0


@dataclass(frozen=True, slots=True)
class CrateConfig:
    id: str
    label: str
    host: str
    system_type: str
    username: str
    password: str
    note: str = ""
    #: Channels the LILAK portal's live wall shows for this crate, in the order
    #: they were ticked: [{"slot": 1, "channel": 0, "name": "Si det"}]. Empty
    #: means the summary counts only.
    live_channels: tuple[dict, ...] = ()
    #: Whether the wall shows this crate's on/trip/alarm counts. A crate that is
    #: registered but not in use (no route to it, powered down for the season)
    #: is turned off here rather than deleted, so its history stays.
    live_summary: bool = True
    #: Minutes between archived snapshots, 0 to keep none on a timer.
    #: The default lives in DEFAULT_ARCHIVE_MIN, not here, because this is a
    #: slotted dataclass -- reading the field off the CLASS gives the slot
    #: descriptor, not the value, and every crate quietly inherited that object
    #: as its interval.
    #:
    #: There has to be a timer. Snapshots used to appear only as a side effect
    #: of elog fills, and when the live wall stopped archiving what it read, the
    #: archive simply stopped -- two days of a crate's history missing with
    #: nothing broken and nothing logged. A history that depends on somebody
    #: else's traffic is not a history.
    archive_interval_min: float = DEFAULT_ARCHIVE_MIN

    def public(self) -> dict[str, Any]:
        """What the browser is allowed to see -- never the password."""
        return {
            "id": self.id,
            "label": self.label,
            "host": self.host,
            "system_type": self.system_type,
            "username": self.username,
            "note": self.note,
            "live_channels": [dict(pick) for pick in self.live_channels],
            "live_summary": self.live_summary,
            "archive_interval_min": self.archive_interval_min,
        }


def _parse(entry: dict[str, Any]) -> CrateConfig:
    missing = [key for key in ("id", "host") if not entry.get(key)]
    if missing:
        raise ValueError(f"crate entry is missing {', '.join(missing)}: {entry!r}")
    return CrateConfig(
        id=str(entry["id"]),
        label=str(entry.get("label") or entry["id"]),
        host=str(entry["host"]),
        system_type=str(entry.get("system_type", "SY5527")),
        username=str(entry.get("username", "admin")),
        password=str(entry.get("password", "admin")),
        note=str(entry.get("note", "")),
        live_channels=clean_live(entry.get("live_channels")),
        live_summary=bool(entry.get("live_summary", True)),
        archive_interval_min=_minutes(entry.get("archive_interval_min")),
    )


def _minutes(value) -> float:
    """The archive interval, in minutes. A missing or unreadable value takes the
    default rather than turning archiving off: silence is how the history went
    missing in the first place."""
    if value is None:
        return DEFAULT_ARCHIVE_MIN
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return DEFAULT_ARCHIVE_MIN


def clean_live(values) -> tuple[dict, ...]:
    """The live picks, as whole slot/channel numbers without repeats. A bad
    entry is dropped rather than refused: a hand-edited file must not stop the
    crate list loading."""
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for value in values or []:
        try:
            slot = int(value["slot"])
            channel = int(value["channel"])
        except (KeyError, TypeError, ValueError):
            continue
        if slot < 0 or channel < 0 or (slot, channel) in seen:
            continue
        seen.add((slot, channel))
        name = str(value.get("name") or "").strip()[:60]
        out.append({"slot": slot, "channel": channel, "name": name})
    return tuple(out)


def load_crates(force: bool = False) -> list[CrateConfig]:
    """Every configured crate.  Cached, because the file rarely changes."""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        if not CRATE_FILE.is_file():
            _cache = []
            return _cache
        raw = json.loads(CRATE_FILE.read_text(encoding="utf-8"))
        entries = raw.get("crates", raw) if isinstance(raw, dict) else raw
        _cache = [_parse(entry) for entry in entries]
        return _cache


def find_crate(crate_id: str) -> CrateConfig | None:
    return next((crate for crate in load_crates() if crate.id == crate_id), None)


def set_live(crate_id: str, picks=None, summary: bool | None = None,
             archive_interval_min: float | None = None) -> CrateConfig:
    """Save what the portal's live wall shows for one crate: which channels, and
    whether its summary counts appear at all.

    The file is rewritten whole (it is a handful of entries) and every other
    field is carried through verbatim -- passwords included, which is why the
    raw file is read again here rather than reconstructed from `public()`.
    """
    cleaned = None if picks is None else clean_live(picks)
    with _lock:
        raw = json.loads(CRATE_FILE.read_text(encoding="utf-8")) if CRATE_FILE.is_file() else {"crates": []}
        wrapped = isinstance(raw, dict)
        entries = raw.get("crates", []) if wrapped else raw
        found = False
        for entry in entries:
            if str(entry.get("id")) == crate_id:
                if cleaned is not None:
                    entry["live_channels"] = [dict(pick) for pick in cleaned]
                if summary is not None:
                    entry["live_summary"] = bool(summary)
                if archive_interval_min is not None:
                    entry["archive_interval_min"] = max(0.0, float(archive_interval_min))
                found = True
        if not found:
            raise KeyError(crate_id)
        CRATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = CRATE_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(raw if wrapped else entries, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(CRATE_FILE)
        global _cache
        _cache = None
    return find_crate(crate_id)
