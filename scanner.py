
import socket
import json
import errno
import time
from datetime import datetime, timezone
from pathlib import Path

PORTS = [21, 22, 25, 53, 80, 443, 3306, 8080]

def _loopback_address(target):
    if not isinstance(target, str) or target not in ("127.0.0.1", "localhost"):
        raise ValueError("Localhost scanning only")
    return "127.0.0.1"

def _scan_port_result(target, port):
    # Validate outside the socket-error handler so invalid targets fail clearly.
    address = _loopback_address(target)
    try:
        # A literal IPv4 address and AF_INET avoid hostname resolution entirely.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.5)
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

def scan_port(target, port):
    """Preserve the original boolean helper; detailed outcomes live in reports."""
    return _scan_port_result(target, port)["status"] == "open"

def scan_target(target="127.0.0.1"):
    # Validate even when no ports are configured; scan_port also guards direct use.
    _loopback_address(target)

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    results = [_scan_port_result(target, port) for port in PORTS]
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
