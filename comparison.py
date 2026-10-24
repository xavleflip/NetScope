"""Compare validated observations without probing ports or changing evidence."""

from datetime import datetime

from reports import validate_report
from validation import loopback_address


def _interpretation(before, after):
    if "not scanned" in (before, after):
        return "Missing coverage: no status transition can be established."
    if {before, after} & {"timeout", "error"}:
        return "Uncertain: timeout/error is not proof that a service started or stopped."
    return {
        ("open", "open"): "Connection succeeded in both observations.",
        ("closed", "closed"): "Connection was explicitly refused in both observations.",
        ("open", "closed"): "Connection succeeded before; the later connection was explicitly refused.",
        ("closed", "open"): "Connection was refused before; the later connection succeeded.",
    }[before, after]


def _metadata(report):
    return {field: report[field] for field in (
        "target", "started_at", "finished_at", "duration_seconds", "timeout_seconds", "summary",
    )}


def compare_reports(baseline, observation):
    """Return deterministic JSON-compatible data, ordered by scan start time.

    Both inputs use the report contract; validation is repeated at this public
    boundary without IO. Reversed inputs are rejected rather than silently
    swapping the user's chosen roles. Equal start times are allowed and noted.
    """
    baseline = validate_report(baseline)
    observation = validate_report(observation)
    earlier = datetime.fromisoformat(baseline["started_at"])
    later = datetime.fromisoformat(observation["started_at"])
    if earlier > later:
        raise ValueError("Baseline starts after the later observation. Swap the two reports.")

    before_rows = {row["port"]: row for row in baseline["results"]}
    after_rows = {row["port"]: row for row in observation["results"]}
    before_ports, after_ports = set(before_rows), set(after_rows)
    summary = dict.fromkeys((
        "total", "status_changed", "status_unchanged", "not_scanned", "uncertain",
        "service_label_changed",
    ), 0)
    rows = []
    for port in sorted(before_ports | after_ports):
        before = before_rows.get(port, {})
        after = after_rows.get(port, {})
        before_status = before.get("status", "not scanned")
        after_status = after.get("status", "not scanned")
        if not before or not after:
            change = "not scanned"
            summary["not_scanned"] += 1
        elif before_status == after_status:
            change = "unchanged"
            summary["status_unchanged"] += 1
        else:
            change = "changed"
            summary["status_changed"] += 1
        uncertain = bool({before_status, after_status} & {"timeout", "error"})
        label_changed = bool(before and after and before["service"] != after["service"])
        summary["total"] += 1
        summary["uncertain"] += int(uncertain)
        summary["service_label_changed"] += int(label_changed)
        rows.append({
            "port": port,
            "before_status": before_status,
            "after_status": after_status,
            "change": change,
            "uncertain": uncertain,
            "before_service": before.get("service"),
            "after_service": after.get("service"),
            "service_label_changed": label_changed,
            "before_error": before.get("error"),
            "after_error": after.get("error"),
            "interpretation": _interpretation(before_status, after_status),
        })

    coverage = {
        "shared": sorted(before_ports & after_ports),
        "baseline_only": sorted(before_ports - after_ports),
        "observation_only": sorted(after_ports - before_ports),
    }
    timeouts_differ = baseline["timeout_seconds"] != observation["timeout_seconds"]
    notes = []
    if earlier == later:
        notes.append("Scan start times are equal; timestamps do not establish an earlier/later order.")
    elif datetime.fromisoformat(baseline["finished_at"]) > later:
        notes.append("Scan time windows overlap; roles are ordered by scan start time.")
    if coverage["baseline_only"] or coverage["observation_only"]:
        notes.append("Scan coverage differs. Missing ports are not scanned, not closed.")
    if timeouts_differ:
        notes.append("Connection timeout settings differ; outcomes may not be directly comparable.")
    return {
        "comparison_version": 1,
        "target": loopback_address(baseline["target"]),
        "baseline": _metadata(baseline),
        "observation": _metadata(observation),
        "coverage": coverage,
        "timeouts_differ": timeouts_differ,
        "notes": notes,
        "summary": summary,
        "results": rows,
    }
