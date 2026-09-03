"""Local bind diagnostics for `bagel dev`.

On Windows, Hyper-V / Docker WinNAT may *temporarily* reserve TCP ranges that
include 8000 (WinError 10013). Ranges move over time — 8000 remains the product
default; we diagnose and only auto-switch when explicitly requested.
"""

from __future__ import annotations

import socket
import subprocess
from typing import Iterable


_FALLBACK_PORTS: tuple[int, ...] = (8001, 8002, 8080, 8888, 9000, 18000)


def can_bind(host: str, port: int) -> bool:
    """Return True if we can bind TCP ``host:port`` right now."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bind_host = "0.0.0.0" if host in {"", "0.0.0.0"} else host
            sock.bind((bind_host, port))
        return True
    except OSError:
        return False


def windows_excluded_tcp_ranges() -> list[tuple[int, int]]:
    """Parse ``netsh … excludedportrange`` (empty on non-Windows / failure)."""
    try:
        completed = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    raw_bytes = completed.stdout or b""
    raw = ""
    for enc in ("utf-8", "gbk", "cp936", "mbcs"):
        try:
            raw = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raw = raw_bytes.decode("utf-8", errors="replace")
    ranges: list[tuple[int, int]] = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            start, end = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if 0 < start <= end <= 65535:
            ranges.append((start, end))
    return ranges


def port_in_excluded_range(port: int, ranges: Iterable[tuple[int, int]] | None = None) -> bool:
    ranges = list(ranges) if ranges is not None else windows_excluded_tcp_ranges()
    return any(start <= port <= end for start, end in ranges)


def listener_pids(port: int) -> list[int]:
    """Best-effort PIDs listening on ``port`` (Windows netstat)."""
    try:
        completed = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    text = (completed.stdout or b"").decode("utf-8", errors="replace")
    pids: list[int] = []
    needle = f":{port}"
    for line in text.splitlines():
        if needle not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def diagnose_bind_failure(host: str, port: int) -> str:
    """Human-readable explanation when ``host:port`` cannot be bound."""
    lines = [f"Cannot bind {host}:{port}."]
    pids = listener_pids(port)
    if pids:
        lines.append(f"Port already in use by PID(s): {', '.join(map(str, pids))}.")
        lines.append("Stop that process, or: netstat -ano | findstr :" + str(port))
    excluded = windows_excluded_tcp_ranges()
    if port_in_excluded_range(port, excluded):
        hit = next(r for r in excluded if r[0] <= port <= r[1])
        lines.append(
            f"Windows temporarily excluded TCP {hit[0]}-{hit[1]} "
            "(WinNAT / Hyper-V / Docker). This is transient — not a Bagel bug."
        )
        lines.append(
            "Fix (Admin PowerShell): net stop winnat && net start winnat"
        )
        lines.append(
            "Or wait a minute and retry; ranges often free after Docker Desktop settles."
        )
    elif not pids:
        lines.append(
            "No listener found; may be a transient WinNAT reservation or permission issue."
        )
        lines.append("Retry once, or (Admin): net stop winnat && net start winnat")
    lines.append(f"Optional: uv run bagel dev --host {host} --port {port} --auto-port")
    return "\n".join(lines)


def resolve_bind_port(
    host: str,
    preferred: int,
    *,
    auto_port: bool = False,
) -> tuple[int, str | None]:
    """Resolve the port to bind.

    Default: keep ``preferred`` (8000) if bindable; otherwise raise with diagnosis.
    With ``auto_port=True``: fall back to nearby free ports.
    """
    if can_bind(host, preferred):
        return preferred, None

    diagnosis = diagnose_bind_failure(host, preferred)
    if not auto_port:
        raise OSError(diagnosis)

    excluded = windows_excluded_tcp_ranges()
    for p in (*_FALLBACK_PORTS, *range(preferred + 1, preferred + 30)):
        if p == preferred:
            continue
        if port_in_excluded_range(p, excluded):
            continue
        if can_bind(host, p):
            return p, f"{diagnosis}\nAuto-switched to {p} (--auto-port)."

    raise OSError(diagnosis + "\nNo free fallback port found.")
