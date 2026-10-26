
import socket
import errno
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from threading import Event

from reports import SCHEMA_VERSION
from validation import (
    MAX_PORTS, MIN_TIMEOUT, MAX_TIMEOUT,
    loopback_address as _loopback_address,
    validate_port as _validate_port,
    validate_timeout as _validate_timeout,
)

PORTS = [21, 22, 25, 53, 80, 443, 3306, 8080]
MAX_WORKERS = 32
DEFAULT_TIMEOUT = 0.5

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

def validate_scan_request(target="127.0.0.1", *, start_port=None, end_port=None, timeout=DEFAULT_TIMEOUT):
    """Validate before launching work, and return the finite requested port list."""
    _loopback_address(target)
    _validate_timeout(timeout)
    ports = tuple(_ports_for_scan(start_port, end_port))
    if len(set(ports)) != len(ports):
        raise ValueError("Requested ports must be unique.")
    return ports


def scan_target(target="127.0.0.1", *, start_port=None, end_port=None, timeout=DEFAULT_TIMEOUT,
                cancel_event=None, on_progress=None):
    """Scan the inclusive range, or the original common ports if no range is given.

    All inputs are checked before any probes. At most MAX_WORKERS sockets run
    concurrently, with at most that many futures in flight. Results retain input
    order regardless of completion order. on_progress(completed, total) runs on
    this caller's thread, including after cancellation as active probes finish.
    A set cancel_event stops scheduling and skips probes not yet started; active
    sockets retain their finite timeout. Return only after all workers are joined.
    """
    # Validate even when no ports are configured; scan_port also guards direct use.
    ports = validate_scan_request(target, start_port=start_port, end_port=end_port, timeout=timeout)
    cancel_event = cancel_event if cancel_event is not None else Event()

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    observed = {}
    if on_progress is not None:
        on_progress(0, len(ports))
    if ports and not cancel_event.is_set():
        pool = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(ports)), thread_name_prefix="netscope-probe")
        pending = set()
        remaining = iter(ports)

        def probe(port):
            # A submitted probe may still be waiting for its worker to start.
            if cancel_event.is_set():
                return None
            return _scan_port_result(target, port, timeout)

        def fill_window():
            while len(pending) < MAX_WORKERS and not cancel_event.is_set():
                port = next(remaining, None)
                if port is None:
                    break
                pending.add(pool.submit(probe, port))

        try:
            fill_window()
            while pending:
                if cancel_event.is_set():
                    for future in pending:
                        future.cancel()
                done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                pending.difference_update(done)
                for future in done:
                    if future.cancelled():
                        continue
                    row = future.result()
                    if row is not None:
                        observed[row["port"]] = row
                        if on_progress is not None:
                            on_progress(len(observed), len(ports))
                fill_window()
        except BaseException:
            cancel_event.set()
            raise
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    results = [observed[port] for port in ports if port in observed]
    duration = time.perf_counter() - started
    summary = {"total": len(results)}
    summary.update({status: sum(row["status"] == status for row in results)
                    for status in ("open", "closed", "timeout", "error")})
    return {
        "schema_version": SCHEMA_VERSION,
        "scan_status": "cancelled" if cancel_event.is_set() else "completed",
        "requested_ports": list(ports),
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
    from cli import main
    raise SystemExit(main())
