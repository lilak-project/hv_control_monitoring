"""Read-only ctypes binding for the CAEN HV Wrapper library.

Why this exists rather than ``caen_hv_py``: that wrapper exposes three values
per channel (VMon, IMon, Pw) through a small shim ``.so``, and its crate map
prints model strings at the wrong offsets. The library underneath it --
``libcaenhvwrapper.so``, declared in ``/usr/include/CAENHVWrapper.h`` -- reports
every parameter the board has (seventeen on an A1542HSN), the channel names the
operator typed into the crate, and a crate map that parses correctly. A
monitoring page wants all of it, so this module talks to that library directly.

Nothing here writes. ``CAENHV_SetChParam`` and friends are deliberately not
bound: a bug in this file cannot move a beamline voltage.

The library keeps per-handle state in process globals and is not thread-safe,
so every call runs under one module-wide lock. Callers must run in a worker
thread -- see ``snapshot.py``.
"""

from __future__ import annotations

import ctypes
import threading
from dataclasses import dataclass, field
from typing import Any

#: Fixed-width record sizes the C API uses for its string lists.
_MAX_PARAM_NAME = 10
_MAX_CH_NAME = 12

_LINKTYPE_TCPIP = 0

#: ``CAENHV_SYSTEM_TYPE_t``.  Only the mainframes we might meet are listed.
SYSTEM_TYPES = {
    "SY1527": 0,
    "SY2527": 1,
    "SY4527": 2,
    "SY5527": 3,
    "N568": 4,
    "V65XX": 5,
    "N1470": 6,
    "V8100": 7,
    "N568E": 8,
    "DT55XX": 9,
    "FTK": 10,
    "DT55XXE": 11,
    "N1068": 12,
    "SMARTHV": 13,
    "NGPS": 14,
}

#: ``PARAM_TYPE_*``.  Decides how a value list is read back.
_TYPE_NUMERIC = 0
_TYPE_ONOFF = 1
_TYPE_CHSTATUS = 2
_TYPE_BDSTATUS = 3
_TYPE_BINARY = 4
_TYPE_STRING = 5
_TYPE_ENUM = 6

TYPE_NAMES = {
    _TYPE_NUMERIC: "numeric",
    _TYPE_ONOFF: "onoff",
    _TYPE_CHSTATUS: "chstatus",
    _TYPE_BDSTATUS: "bdstatus",
    _TYPE_BINARY: "binary",
    _TYPE_STRING: "string",
    _TYPE_ENUM: "enum",
}

MODE_NAMES = {0: "ro", 1: "wo", 2: "rw"}

#: ``PARAM_UN_*`` to the symbol an operator reads.
_UNIT_SYMBOLS = {
    0: "",
    1: "A",
    2: "V",
    3: "W",
    4: "°C",
    5: "Hz",
    6: "bar",
    7: "V/s",
    8: "s",
    9: "rpm",
    10: "cnt",
    11: "bit",
    12: "A/s",
}

_SI_PREFIXES = {-12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}

#: Error codes worth a sentence of their own.  Everything else falls back to
#: ``CAENHV_GetError``, or to the bare number when even that is empty.
_ERROR_TEXT = {
    1: "system error",
    2: "write error",
    3: "read error",
    4: "timeout",
    5: "crate is down",
    6: "not present",
    7: "slot not present",
    9: "memory fault",
    10: "value out of range",
    22: "parameter not found",
    23: "no data",
    26: "invalid parameter",
    28: "socket error",
    29: "communication error",
    0x1000 + 2: "not connected",
    0x1000 + 3: "operating system error",
    0x1000 + 4: "login failed - crate unreachable, or busy with another session",
    0x1000 + 5: "logout failed",
    0x1000 + 6: "link type not supported",
    0x1000 + 7: "username or password rejected",
}

#: Bit meanings of the CHSTATUS word on SY4527/SY5527 HV boards.  ``True``
#: marks a bit that is a fault rather than a state, so the UI can colour it.
CH_STATUS_BITS: tuple[tuple[str, bool], ...] = (
    ("On", False),
    ("Ramp up", False),
    ("Ramp down", False),
    ("Over current", True),
    ("Over voltage", True),
    ("Under voltage", True),
    ("External trip", True),
    ("Max V", True),
    ("External disable", True),
    ("Internal trip", True),
    ("Calibration error", True),
    ("Unplugged", True),
    ("", False),
    ("Over voltage protection", True),
    ("Power fail", True),
    ("Temperature error", True),
)


class CaenError(RuntimeError):
    """A call into the CAEN library failed."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class CaenBusy(CaenError):
    """Another read is already using the library, and did not finish in time."""


def _describe(code: int, detail: str = "") -> str:
    text = _ERROR_TEXT.get(code, f"error {code}")
    detail = detail.strip()
    return f"{text} ({detail})" if detail and detail.lower() not in text.lower() else text


def unit_label(unit: int, exp: int) -> str:
    """``(1, -6)`` -> ``"uA"``: the unit a value should be shown in."""
    symbol = _UNIT_SYMBOLS.get(unit, "")
    if not symbol:
        return ""
    prefix = _SI_PREFIXES.get(exp)
    if prefix is None:
        # An exponent with no SI prefix; say it plainly rather than lie.
        return f"1e{exp} {symbol}"
    return prefix + symbol


def decode_status(raw: int) -> list[str]:
    """The set bits of a CHSTATUS word, named."""
    return [name for bit, (name, _) in enumerate(CH_STATUS_BITS) if name and raw >> bit & 1]


def status_is_fault(raw: int) -> bool:
    return any(fault and raw >> bit & 1 for bit, (_, fault) in enumerate(CH_STATUS_BITS))


@dataclass(slots=True)
class ParamSpec:
    """What one channel parameter is, as the board describes itself."""

    name: str
    type: str
    mode: str
    unit: str = ""
    exp: int = 0
    minval: float | None = None
    maxval: float | None = None
    #: For on/off parameters, the words the crate itself uses.
    on_state: str = "On"
    off_state: str = "Off"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "mode": self.mode,
            "unit": self.unit,
            "exp": self.exp,
            "min": self.minval,
            "max": self.maxval,
            "on_state": self.on_state,
            "off_state": self.off_state,
        }


@dataclass(slots=True)
class Board:
    """One populated slot."""

    slot: int
    model: str
    description: str
    serial: int
    firmware: str
    channels: int
    params: list[ParamSpec] = field(default_factory=list)


_lib: ctypes.CDLL | None = None
_lib_lock = threading.Lock()
#: The library is not thread-safe; one call at a time, process-wide.
CALL_LOCK = threading.RLock()


def load_library() -> ctypes.CDLL:
    """Load ``libcaenhvwrapper.so`` once and declare the prototypes we use."""
    global _lib
    with _lib_lock:
        if _lib is not None:
            return _lib
        try:
            lib = ctypes.CDLL("libcaenhvwrapper.so")
        except OSError as err:
            raise CaenError(
                "libcaenhvwrapper.so is not installed on this host "
                f"({err}). Install the CAEN HV Wrapper before using this service."
            ) from err

        c_ushort_p = ctypes.POINTER(ctypes.c_ushort)
        c_ubyte_p = ctypes.POINTER(ctypes.c_ubyte)

        lib.CAENHVLibSwRel.restype = ctypes.c_char_p
        lib.CAENHVLibSwRel.argtypes = []

        lib.CAENHV_InitSystem.restype = ctypes.c_int
        lib.CAENHV_InitSystem.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
        ]

        lib.CAENHV_DeinitSystem.restype = ctypes.c_int
        lib.CAENHV_DeinitSystem.argtypes = [ctypes.c_int]

        lib.CAENHV_GetCrateMap.restype = ctypes.c_int
        lib.CAENHV_GetCrateMap.argtypes = [
            ctypes.c_int,
            c_ushort_p,
            ctypes.POINTER(c_ushort_p),
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(c_ushort_p),
            ctypes.POINTER(c_ubyte_p),
            ctypes.POINTER(c_ubyte_p),
        ]

        lib.CAENHV_GetChParamInfo.restype = ctypes.c_int
        lib.CAENHV_GetChParamInfo.argtypes = [
            ctypes.c_int,
            ctypes.c_ushort,
            ctypes.c_ushort,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_int),
        ]

        lib.CAENHV_GetChParamProp.restype = ctypes.c_int
        lib.CAENHV_GetChParamProp.argtypes = [
            ctypes.c_int,
            ctypes.c_ushort,
            ctypes.c_ushort,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_void_p,
        ]

        lib.CAENHV_GetChParam.restype = ctypes.c_int
        lib.CAENHV_GetChParam.argtypes = [
            ctypes.c_int,
            ctypes.c_ushort,
            ctypes.c_char_p,
            ctypes.c_ushort,
            c_ushort_p,
            ctypes.c_void_p,
        ]

        lib.CAENHV_GetChName.restype = ctypes.c_int
        lib.CAENHV_GetChName.argtypes = [
            ctypes.c_int,
            ctypes.c_ushort,
            ctypes.c_ushort,
            c_ushort_p,
            ctypes.c_void_p,
        ]

        lib.CAENHV_GetError.restype = ctypes.c_char_p
        lib.CAENHV_GetError.argtypes = [ctypes.c_int]

        lib.CAENHV_Free.restype = ctypes.c_int
        lib.CAENHV_Free.argtypes = [ctypes.c_void_p]

        _lib = lib
        return lib


def library_release() -> str:
    try:
        value = load_library().CAENHVLibSwRel()
    except CaenError:
        return ""
    return value.decode(errors="replace") if value else ""


def _split_packed(pointer: Any, count: int) -> list[str]:
    """``count`` NUL-terminated strings laid end to end, as the crate map returns them."""
    base = ctypes.cast(pointer, ctypes.c_void_p).value
    if base is None:
        return [""] * count
    out: list[str] = []
    offset = 0
    for _ in range(count):
        raw = ctypes.cast(base + offset, ctypes.c_char_p).value or b""
        out.append(raw.decode(errors="replace").strip())
        offset += len(raw) + 1
    return out


def _split_fixed(pointer: Any, count: int, stride: int) -> list[str]:
    """``count`` strings in fixed-width slots, as the parameter list returns them."""
    base = ctypes.cast(pointer, ctypes.c_void_p).value
    if base is None:
        return []
    out: list[str] = []
    for index in range(count):
        raw = ctypes.cast(base + index * stride, ctypes.c_char_p).value or b""
        text = raw.decode(errors="replace").strip()
        if not text:
            continue
        out.append(text)
    return out


class CaenSession:
    """One login to one crate, for the length of one sweep.

    The crate drops a session that has been idle for about fifteen seconds, so
    there is no connection to keep alive between requests: a snapshot logs in,
    reads, and logs out. That is a third of a second against a reachable crate.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        system_type: str = "SY5527",
        busy_timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.system_type = system_type
        self.busy_timeout = busy_timeout
        self.handle: int | None = None
        self._lib = load_library()
        if system_type not in SYSTEM_TYPES:
            raise CaenError(
                f"unknown system type {system_type!r}; expected one of {', '.join(SYSTEM_TYPES)}"
            )

    # -- lifecycle ----------------------------------------------------------

    def __enter__(self) -> CaenSession:
        # One sweep at a time, and never an unbounded wait: a caller who
        # arrives while another crate is being read is told so.
        if not CALL_LOCK.acquire(timeout=self.busy_timeout):
            raise CaenBusy(
                f"another crate read has held the CAEN library for over "
                f"{self.busy_timeout:g} s; try again shortly"
            )
        try:
            self._login()
        except BaseException:
            CALL_LOCK.release()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            if self.handle is not None:
                self._lib.CAENHV_DeinitSystem(self.handle)
                self.handle = None
        finally:
            CALL_LOCK.release()

    def _login(self) -> None:
        handle = ctypes.c_int(-1)
        # InitSystem takes the address as a mutable buffer, not a const char*.
        arg = ctypes.create_string_buffer(self.host.encode())
        code = self._lib.CAENHV_InitSystem(
            SYSTEM_TYPES[self.system_type],
            _LINKTYPE_TCPIP,
            ctypes.cast(arg, ctypes.c_void_p),
            self.username.encode(),
            self.password.encode(),
            ctypes.byref(handle),
        )
        if code != 0:
            raise CaenError(f"{self.host}: {_describe(code)}", code)
        self.handle = handle.value

    def _error_detail(self) -> str:
        if self.handle is None:
            return ""
        raw = self._lib.CAENHV_GetError(self.handle)
        return raw.decode(errors="replace").strip() if raw else ""

    def _check(self, code: int, what: str) -> None:
        if code != 0:
            raise CaenError(f"{what}: {_describe(code, self._error_detail())}", code)

    # -- reads --------------------------------------------------------------

    def crate_map(self) -> list[Board]:
        """Every populated slot, with the model and firmware it reports."""
        assert self.handle is not None
        slots = ctypes.c_ushort(0)
        n_channels = ctypes.POINTER(ctypes.c_ushort)()
        models = ctypes.c_char_p()
        descriptions = ctypes.c_char_p()
        serials = ctypes.POINTER(ctypes.c_ushort)()
        fw_min = ctypes.POINTER(ctypes.c_ubyte)()
        fw_max = ctypes.POINTER(ctypes.c_ubyte)()

        code = self._lib.CAENHV_GetCrateMap(
            self.handle,
            ctypes.byref(slots),
            ctypes.byref(n_channels),
            ctypes.byref(models),
            ctypes.byref(descriptions),
            ctypes.byref(serials),
            ctypes.byref(fw_min),
            ctypes.byref(fw_max),
        )
        self._check(code, "crate map")

        try:
            count = slots.value
            model_list = _split_packed(models, count)
            description_list = _split_packed(descriptions, count)
            boards = [
                Board(
                    slot=slot,
                    model=model_list[slot],
                    description=description_list[slot],
                    serial=serials[slot],
                    firmware=f"{fw_min[slot]}.{fw_max[slot]}",
                    channels=n_channels[slot],
                )
                for slot in range(count)
                # An empty slot reports zero channels and blank strings.
                if n_channels[slot] > 0
            ]
        finally:
            for pointer in (n_channels, models, descriptions, serials, fw_min, fw_max):
                self._lib.CAENHV_Free(ctypes.cast(pointer, ctypes.c_void_p))
        return boards

    def param_specs(self, slot: int) -> list[ParamSpec]:
        """The parameters a board's channels carry, described by the board itself.

        Asked of channel 0: every channel on a board is the same kind of
        channel, and asking twenty-four times would only be slower.
        """
        assert self.handle is not None
        buffer = ctypes.c_char_p()
        count = ctypes.c_int(0)
        code = self._lib.CAENHV_GetChParamInfo(
            self.handle, slot, 0, ctypes.byref(buffer), ctypes.byref(count)
        )
        self._check(code, f"slot {slot} parameter list")
        try:
            names = _split_fixed(buffer, count.value, _MAX_PARAM_NAME)
        finally:
            self._lib.CAENHV_Free(ctypes.cast(buffer, ctypes.c_void_p))

        return [spec for name in names if (spec := self._param_spec(slot, name)) is not None]

    def _prop(self, slot: int, name: str, prop: str, ctype: Any) -> Any | None:
        """One property of one parameter, or None when the board has no such property.

        The library writes into the caller's buffer without being told how big
        it is, so every read goes into a generous one and is cast down.
        """
        assert self.handle is not None
        buffer = ctypes.create_string_buffer(1024)
        code = self._lib.CAENHV_GetChParamProp(
            self.handle, slot, 0, name.encode(), prop.encode(), ctypes.byref(buffer)
        )
        if code != 0:
            return None
        return ctypes.cast(buffer, ctypes.POINTER(ctype)).contents.value

    def _param_spec(self, slot: int, name: str) -> ParamSpec | None:
        type_code = self._prop(slot, name, "Type", ctypes.c_uint)
        if type_code is None or type_code not in TYPE_NAMES:
            return None
        mode_code = self._prop(slot, name, "Mode", ctypes.c_uint)
        spec = ParamSpec(
            name=name,
            type=TYPE_NAMES[type_code],
            mode=MODE_NAMES.get(mode_code if mode_code is not None else 0, "ro"),
        )
        if type_code == _TYPE_NUMERIC:
            unit = self._prop(slot, name, "Unit", ctypes.c_ushort) or 0
            exp = self._prop(slot, name, "Exp", ctypes.c_short) or 0
            spec.unit = unit_label(unit, exp)
            spec.exp = exp
            spec.minval = self._prop(slot, name, "Minval", ctypes.c_float)
            spec.maxval = self._prop(slot, name, "Maxval", ctypes.c_float)
        elif type_code == _TYPE_ONOFF:
            on_state = self._string_prop(slot, name, "Onstate")
            off_state = self._string_prop(slot, name, "Offstate")
            spec.on_state = on_state or "On"
            spec.off_state = off_state or "Off"
        return spec

    def _string_prop(self, slot: int, name: str, prop: str) -> str:
        assert self.handle is not None
        buffer = ctypes.create_string_buffer(1024)
        code = self._lib.CAENHV_GetChParamProp(
            self.handle, slot, 0, name.encode(), prop.encode(), ctypes.byref(buffer)
        )
        if code != 0:
            return ""
        return buffer.value.decode(errors="replace").strip()

    def channel_names(self, slot: int, channels: int) -> list[str]:
        """The names an operator typed into the crate, one per channel."""
        assert self.handle is not None
        ch_list = (ctypes.c_ushort * channels)(*range(channels))
        names = ((ctypes.c_char * _MAX_CH_NAME) * channels)()
        code = self._lib.CAENHV_GetChName(
            self.handle, slot, channels, ch_list, ctypes.byref(names)
        )
        if code != 0:
            # Names are a convenience; a board that will not give them up must
            # not cost us the readings.
            return [""] * channels
        return [bytes(entry).split(b"\0", 1)[0].decode(errors="replace").strip() for entry in names]

    def read_param(self, slot: int, spec: ParamSpec, channels: int) -> list[Any] | None:
        """One parameter across every channel of a board, in one call."""
        assert self.handle is not None
        ch_list = (ctypes.c_ushort * channels)(*range(channels))

        if spec.type == "numeric":
            values: Any = (ctypes.c_float * channels)()
        elif spec.type in ("onoff", "chstatus", "bdstatus", "binary", "enum"):
            values = (ctypes.c_uint * channels)()
        else:
            # Strings would need a 1 kB slot per channel and no board here uses
            # one; skip rather than guess at the layout.
            return None

        code = self._lib.CAENHV_GetChParam(
            self.handle, slot, spec.name.encode(), channels, ch_list, values
        )
        if code != 0:
            return None
        if spec.type == "numeric":
            return [round(float(value), 6) for value in values]
        return [int(value) for value in values]
