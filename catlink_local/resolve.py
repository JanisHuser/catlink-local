"""Clean upstream DNS resolution.

In proxy mode we must reach the *real* CATLINK cloud, but our own DNS server
poisons ``*.catlinks.cn`` to point at this box.  If the proxy resolved an
upstream hostname through that same DNS it would connect back to itself.

This module resolves a hostname by talking UDP DNS directly to a clean resolver
(default 1.1.1.1), bypassing the local poison.  IP literals are returned as-is.
Results are cached with a short TTL.  Pure standard library.
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import socket
import struct
import time

_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 300.0


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _build_query(host: str) -> tuple[int, bytes]:
    tid = random.randint(0, 0xFFFF)
    header = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)  # RD=1, 1 question
    qname = b"".join(bytes([len(p)]) + p.encode() for p in host.split(".") if p) + b"\x00"
    question = qname + struct.pack(">HH", 1, 1)  # QTYPE=A, QCLASS=IN
    return tid, header + question


def _parse_answer(data: bytes) -> str | None:
    if len(data) < 12:
        return None
    ancount = struct.unpack(">H", data[6:8])[0]
    idx = 12
    # skip the question's qname
    while idx < len(data) and data[idx] != 0:
        if data[idx] & 0xC0 == 0xC0:  # compression pointer
            idx += 2
            break
        idx += 1 + data[idx]
    else:
        idx += 1
    idx += 4  # qtype + qclass
    for _ in range(ancount):
        if idx + 2 > len(data):
            break
        if data[idx] & 0xC0 == 0xC0:  # name pointer
            idx += 2
        else:
            while idx < len(data) and data[idx] != 0:
                idx += 1 + data[idx]
            idx += 1
        if idx + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[idx : idx + 10])
        idx += 10
        if rtype == 1 and rdlen == 4:  # A record
            return ".".join(str(b) for b in data[idx : idx + 4])
        idx += rdlen
    return None


def _resolve_blocking(host: str, server: str, port: int, timeout: float) -> str | None:
    _tid, pkt = _build_query(host)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(pkt, (server, port))
        data, _ = s.recvfrom(1024)
    except OSError:
        return None
    finally:
        s.close()
    return _parse_answer(data)


async def resolve(host: str, server: str = "1.1.1.1", port: int = 53, timeout: float = 3.0) -> str:
    """Resolve ``host`` to an IPv4 address via a clean resolver.

    Falls back to the system resolver if the clean query fails, and ultimately
    to the hostname itself (so a misconfiguration surfaces as a connect error
    rather than a silent wrong-IP).
    """
    if _is_ip(host):
        return host
    now = time.time()
    cached = _cache.get(host)
    if cached and cached[1] > now:
        return cached[0]

    ip = await asyncio.to_thread(_resolve_blocking, host, server, port, timeout)
    if ip is None:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, None, family=socket.AF_INET
            )
            ip = infos[0][4][0] if infos else None
        except OSError:
            ip = None
    result = ip or host
    _cache[host] = (result, now + _CACHE_TTL)
    return result
