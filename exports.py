"""Shared report serialization and atomic publication to caller-chosen paths."""

import csv
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unicodedata

from reports import scan_details, validate_report


CSV_COLUMNS = (
    "target", "started_at", "scan_status", "requested_count", "completed_count",
    "port", "service", "status", "error",
)


def _spreadsheet_text(value):
    """Make risky leading text literal, including hidden/control prefixes."""
    index = 0
    control_prefix = False
    while index < len(value):
        control = unicodedata.category(value[index]) in ("Cc", "Cf")
        if not (value[index].isspace() or control):
            break
        control_prefix |= control
        index += 1
    if control_prefix or value[index:index + 1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def serialize_report(report, output_format="json"):
    """Export all evidence; CSV additionally makes missing coverage explicit."""
    report = validate_report(report)
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if output_format != "csv":
        raise ValueError("Output format must be json or csv.")
    details = scan_details(report)
    requested = details["requested_ports"]
    metadata = {"target": report["target"], "started_at": report["started_at"],
                "scan_status": details["scan_status"], "requested_count": len(requested),
                "completed_count": report["summary"]["total"]}
    by_port = {row["port"]: row for row in report["results"]}
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    # A metadata-only row keeps an empty report's completion status identifiable.
    for port in requested or [None]:
        row = by_port.get(port, {})
        writer.writerow({**metadata, "port": "" if port is None else port,
                         "service": _spreadsheet_text(row.get("service", "")),
                         "status": row.get("status", "not scanned" if port is not None else ""),
                         "error": _spreadsheet_text(row.get("error", ""))})
    return stream.getvalue()


def write_report(destination, text, *, overwrite=False):
    """Publish a complete UTF-8 file atomically, never clobbering by default.

    A same-directory hard link provides atomic create-if-absent publication.
    Explicit overwrite uses os.replace. Unsupported filesystems fail safely.
    """
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=destination.parent, prefix=".netscope-",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
