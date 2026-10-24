
import socket
import json
import errno
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

PORTS = [21, 22, 25, 53, 80, 443, 3306, 8080]
MAX_PORTS = 1024
MAX_WORKERS = 32
MIN_TIMEOUT = 0.05
MAX_TIMEOUT = 2.0
DEFAULT_TIMEOUT = 0.5

def _loopback_address(target):
    if not isinstance(target, str) or target not in ("127.0.0.1", "localhost"):
        raise ValueError("Localhost scanning only")
    return "127.0.0.1"

def _validate_port(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Ports must be integers within 1–65535.")

def _validate_timeout(timeout):
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT):
        raise ValueError(f"Timeout must be {MIN_TIMEOUT}–{MAX_TIMEOUT} seconds.")

def _ports_for_scan(start_port, end_port):
    if start_port is None and end_port is None:
        # Preserve the original eight-port scan for existing callers and the CLI.
        ports = tuple(PORTS)
        for port in ports:
            _validate_port(port)
    else:
        _validate_port(start_port)
        _validate_port(end_port)
        if start_port > end_port:
            raise ValueError("Start port must be less than or equal to end port.")
        ports = range(start_port, end_port + 1)
    if len(ports) > MAX_PORTS:
        raise ValueError(f"Scan at most {MAX_PORTS} ports at a time.")
    return ports

def _scan_port_result(target, port, timeout=DEFAULT_TIMEOUT):
    # Validate outside the socket-error handler so invalid targets fail clearly.
    address = _loopback_address(target)
    _validate_port(port)
    _validate_timeout(timeout)
    try:
        # A literal IPv4 address and AF_INET avoid hostname resolution entirely.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect((address, port))
        status = "open"
        error = None
    except OSError as exc:
        code = getattr(exc, "winerror", None) or exc.errno
        if isinstance(exc, ConnectionRefusedError) or code in (errno.ECONNREFUSED, 10061):
            status = "closed"
        elif isinstance(exc, TimeoutError) or code in (errno.ETIMEDOUT, 10060):
            status = "timeout"
        else:
            status = "error"
        error = str(exc)

    # The OS lookup provides a conventional assignment, not protocol detection.
    try:
        service = socket.getservbyport(port, "tcp")
    except OSError:
        service = "unknown"
    result = {"port": port, "service": service, "status": status}
    if status == "error":
        result["error"] = error
    return result

def scan_port(target, port, timeout=DEFAULT_TIMEOUT):
    """Preserve the original boolean helper; detailed outcomes live in reports."""
    return _scan_port_result(target, port, timeout)["status"] == "open"

def scan_target(target="127.0.0.1", *, start_port=None, end_port=None, timeout=DEFAULT_TIMEOUT):
    """Scan the inclusive range, or the original common ports if no range is given.

    All inputs are checked before any probes. At most MAX_WORKERS sockets run
    concurrently, and results retain input order regardless of completion order.
    """
    # Validate even when no ports are configured; scan_port also guards direct use.
    _loopback_address(target)
    _validate_timeout(timeout)
    ports = _ports_for_scan(start_port, end_port)

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    results = []
    if ports:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(ports))) as pool:
            results = list(pool.map(lambda port: _scan_port_result(target, port, timeout), ports))
    duration = time.perf_counter() - started
    summary = {"total": len(results)}
    summary.update({status: sum(row["status"] == status for row in results)
                    for status in ("open", "closed", "timeout", "error")})
    return {
        "target": target,
        "timestamp": started_at,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 6),
        "timeout_seconds": float(timeout),
        "summary": summary,
        "results": results,
        "open_ports": [{"port": row["port"], "service": row["service"]}
                       for row in results if row["status"] == "open"],
    }

if __name__ == "__main__":
    result = scan_target()
    print(json.dumps(result, indent=2))

    Path("reports").mkdir(exist_ok=True)
    Path("reports/scan.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8"
    )
