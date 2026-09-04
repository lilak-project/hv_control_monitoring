"""The list of crates this service can reach, read from ``data/crates.json``."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from .config import CRATE_FILE

_lock = threading.Lock()
_cache: list[CrateConfig] | None = None


@dataclass(frozen=True, slots=True)
class CrateConfig:
    id: str
    label: str
    host: str
    system_type: str
    username: str
    password: str
    note: str = ""

    def public(self) -> dict[str, Any]:
        """What the browser is allowed to see -- never the password."""
        return {
            "id": self.id,
            "label": self.label,
            "host": self.host,
            "system_type": self.system_type,
            "username": self.username,
            "note": self.note,
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
    )


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
