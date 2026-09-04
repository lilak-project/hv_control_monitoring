"""Work out which URLs an operator can actually open this server on.

The host sits on several networks at once -- the instrument subnet, the lab
LAN, and a VPN overlay -- and the server binds all of them. Guessing one address
from the hostname misses most of them, so the interfaces are enumerated
directly and every working URL is offered.
"""

from __future__ import annotations

import socket
import struct

#: The lab instruments live on 192.168.1.0/24, so that address is listed first.
_PREFERRED_PREFIX = "192.168.1."

# Linux ioctls for reading an interface's address and flags.
_SIOCGIFADDR = 0x8915
_SIOCGIFFLAGS = 0x8913
_IFF_UP = 0x1
_IFF_RUNNING = 0x40


def _routed_address() -> str | None:
    """Source address the kernel would use to reach the instrument subnet."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((_PREFERRED_PREFIX + "1", 80))
            address = sock.getsockname()[0]
    except OSError:
        return None
    return address if address and not address.startswith("127.") else None


def _interface_addresses() -> list[str]:
    """IPv4 address of every interface that is up and running (Linux only)."""
    try:
        import fcntl
    except ImportError:  # not Linux; the fallbacks below still apply
        return []

    addresses: list[str] = []
    try:
        names = [name for _, name in socket.if_nameindex()]
    except OSError:
        return []

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for name in names:
            request = struct.pack("256s", name[:15].encode())
            try:
                flags = struct.unpack(
                    "H", fcntl.ioctl(sock.fileno(), _SIOCGIFFLAGS, request)[16:18]
                )[0]
                if not (flags & _IFF_UP and flags & _IFF_RUNNING):
                    continue
                packed = fcntl.ioctl(sock.fileno(), _SIOCGIFADDR, request)
            except OSError:
                # No IPv4 on this interface, or it went away mid-scan.
                continue
            addresses.append(socket.inet_ntoa(packed[20:24]))
    return addresses


def _hostname_addresses() -> list[str]:
    try:
        return list(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        return []


def lan_addresses() -> list[str]:
    """Every address this server can be reached on, best guess first."""
    found: list[str] = []
    for address in [_routed_address(), *_interface_addresses(), *_hostname_addresses()]:
        if address and not address.startswith("127.") and address not in found:
            found.append(address)
    return found


def browser_url(host: str, port: int) -> str:
    """The single URL to lead with; the caller lists the rest."""
    if host in ("127.0.0.1", "localhost"):
        return f"http://127.0.0.1:{port}"
    addresses = lan_addresses()
    preferred = next((ip for ip in addresses if ip.startswith(_PREFERRED_PREFIX)), None)
    preferred = preferred or (addresses[0] if addresses else None)
    if preferred:
        return f"http://{preferred}:{port}"
    return f"http://<this-server>:{port}"
