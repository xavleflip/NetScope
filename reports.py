"""Validate report data without scanning, executing content, or reading files."""

from datetime import datetime
import json
import math
import re

from validation import MAX_PORTS, loopback_address, validate_port, validate_timeout


SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 1024 * 1024
STATUSES = ("open", "closed", "timeout", "error")
_FIELDS = {
    "target", "timestamp", "started_at", "finished_at", "duration_seconds",
    "timeout_seconds", "summary", "results", "open_ports",
}
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)")


def _check_fields(value, required, name, optional=()):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object.")
    missing = required - value.keys()
    if missing:
        raise ValueError(f"{name} is missing required fields: {', '.join(sorted(missing))}.")
    if value.keys() - required - set(optional):
        raise ValueError(f"{name} contains unsupported fields.")


def _text(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} contains invalid Unicode.") from exc
    return value


def _timestamp(value, name):
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        raise ValueError(f"{name} must be a UTC ISO timestamp ending in Z or +00:00.")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid timestamp.") from exc


def _duration(value):
    if type(value) not in (int, float) or value < 0:
        raise ValueError("duration_seconds must be a finite, non-negative number.")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("duration_seconds must be a finite, non-negative number.")


def validate_report(report):
    """Return an independent version-1 report; never mutate the input.

    Unversioned reports with the current legacy shape are version 1. Validation
    establishes structure and internal consistency, not measurement authenticity.
    Use load_report for the byte-size boundary on external JSON.
    """
    _check_fields(report, _FIELDS, "Report", optional={"schema_version"})
    version = report.get("schema_version", SCHEMA_VERSION)
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError("Unsupported schema_version; only version 1 is accepted.")
    loopback_address(report["target"])
    started = _timestamp(report["started_at"], "started_at")
    timestamp = _timestamp(report["timestamp"], "timestamp")
    finished = _timestamp(report["finished_at"], "finished_at")
    if timestamp != started:
        raise ValueError("timestamp must describe the same instant as started_at.")
    if finished < started:
        raise ValueError("finished_at must not precede started_at.")
    # Wall-clock elapsed time need not match the monotonic duration exactly.
    _duration(report["duration_seconds"])
    validate_timeout(report["timeout_seconds"])

    raw_results = report["results"]
    if not isinstance(raw_results, list) or len(raw_results) > MAX_PORTS:
        raise ValueError(f"results must be a list of at most {MAX_PORTS} rows.")
    results = []
    ports = set()
    expected_summary = {"total": len(raw_results), **dict.fromkeys(STATUSES, 0)}
    for raw in raw_results:
        _check_fields(raw, {"port", "service", "status"}, "Result", optional={"error"})
        validate_port(raw["port"])
        if raw["port"] in ports:
            raise ValueError("Duplicate result ports are not allowed.")
        ports.add(raw["port"])
        service = _text(raw["service"], "Result service")
        if not service:
            raise ValueError("Result service must not be empty; use unknown if unavailable.")
        status = raw["status"]
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError("Result status must be open, closed, timeout, or error.")
        row = {"port": raw["port"], "service": service, "status": status}
        if status == "error":
            if "error" not in raw:
                raise ValueError("An error result must include an error message.")
            row["error"] = _text(raw["error"], "Result error")
        elif "error" in raw:
            raise ValueError("Only error results may contain an error message.")
        results.append(row)
        expected_summary[status] += 1

    summary = report["summary"]
    _check_fields(summary, {"total", *STATUSES}, "summary")
    if any(type(count) is not int or not 0 <= count <= MAX_PORTS for count in summary.values()):
        raise ValueError("summary counts must be non-negative integers within the port limit.")
    if summary != expected_summary:
        raise ValueError("summary counts do not agree with results.")

    expected_open = [{"port": row["port"], "service": row["service"]}
                     for row in results if row["status"] == "open"]
    raw_open = report["open_ports"]
    if not isinstance(raw_open, list) or len(raw_open) > MAX_PORTS:
        raise ValueError("open_ports must be a list within the port limit.")
    open_by_port = {}
    for row in raw_open:
        _check_fields(row, {"port", "service"}, "open_ports row")
        validate_port(row["port"])
        _text(row["service"], "open_ports service")
        if row["port"] in open_by_port:
            raise ValueError("Duplicate open_ports entries are not allowed.")
        open_by_port[row["port"]] = row["service"]
    if open_by_port != {row["port"]: row["service"] for row in expected_open}:
        raise ValueError("open_ports does not agree with the open results.")

    return {
        "schema_version": SCHEMA_VERSION,
        "target": report["target"],
        "timestamp": timestamp.isoformat(),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": report["duration_seconds"],
        "timeout_seconds": report["timeout_seconds"],
        "summary": expected_summary,
        "results": results,
        "open_ports": expected_open,
    }


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not allowed.")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON numbers are not allowed.")


def load_report(data):
    """Load at most 1 MiB of UTF-8 JSON bytes, optionally with a UTF-8 BOM."""
    if not isinstance(data, bytes):
        raise ValueError("Report input must be UTF-8 JSON bytes.")
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("Report exceeds the 1 MiB import limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Report must use UTF-8 encoding.") from exc
    try:
        report = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid JSON: malformed content, duplicate keys, or non-finite numbers.") from exc
    return validate_report(report)
