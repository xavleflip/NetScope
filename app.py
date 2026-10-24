
import json

import streamlit as st

from scanner import DEFAULT_TIMEOUT, MAX_PORTS, MAX_TIMEOUT, MAX_WORKERS, MIN_TIMEOUT, scan_target
from reports import MAX_REPORT_BYTES, load_report
from history import HistoryError, delete_report, list_reports, load_saved_report, save_report
from comparison import compare_reports


def read_uploaded_report(uploaded):
    """Apply the same bounded read to ordinary and comparison imports."""
    uploaded.seek(0)
    return load_report(uploaded.read(MAX_REPORT_BYTES + 1))


def render_report(report, *, source="scan", scan_id=None):
    """Keep scan, import, and saved evidence controls independent."""
    heading, download_label, filename = {
        "scan": ("Latest scan", "Download JSON Report", "scan.json"),
        "imported": ("Imported report", "Download imported JSON report", "imported-report.json"),
        "history": (f"Saved report #{scan_id}", "Download saved JSON report", f"saved-report-{scan_id}.json"),
    }[source]
    st.subheader(heading)
    if source != "scan":
        description = "Imported" if source == "imported" else "Saved"
        st.caption(f"{description} observation, not a new scan. Validation checks format and "
                   "consistency, not the authenticity of the measurements.")
    st.caption(f"Target: {report['target']} · Ports checked: {report['summary']['total']} · "
               f"Started: {report['started_at']} · "
               f"Timeout: {report['timeout_seconds']:g}s · "
               f"Duration: {report['duration_seconds']:.3f}s")
    for column, status in zip(st.columns(4), ("open", "closed", "timeout", "error")):
        column.metric("Open Ports" if status == "open" else status.title(),
                      report["summary"][status])
    only_open = st.checkbox("Show only open ports", key=f"{source}_only_open")
    rows = [row for row in report["results"] if not only_open or row["status"] == "open"]
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.info("No open ports found in this scan." if only_open else "Report contains no port results.")
    st.download_button(download_label, data=json.dumps(report, indent=2), file_name=filename,
                       mime="application/json", on_click="ignore", key=f"{source}_download")
    if source != "history" and st.button("Save report", key=f"{source}_save"):
        try:
            saved_id = save_report(report)
            st.success(f"Report is stored in local history as #{saved_id}.")
        except (HistoryError, ValueError) as exc:
            st.error(f"Save failed: {exc}")


def render_comparison():
    st.subheader("Compare reports")
    st.caption("Choose the earlier baseline and later observation by scan start time. "
               "Comparing does not scan or save history. Validation does not prove authenticity.")
    source = st.radio("Comparison source", ("Saved history", "JSON files"), key="comparison_source")
    try:
        if source == "Saved history":
            entries = list_reports()
            if not entries:
                st.caption("Save reports to history, or choose JSON files to compare two uploads.")
                return
            by_id = {entry["id"]: entry for entry in entries}
            selected = []
            for role, label in (("baseline", "Earlier baseline"), ("observation", "Later observation")):
                key = f"comparison_{role}_id"
                if st.session_state.get(key) not in by_id:
                    st.session_state.pop(key, None)
                selected.append(st.selectbox(
                    label, options=list(by_id), index=None, key=key,
                    format_func=lambda scan_id: f"#{scan_id} · {by_id[scan_id]['started_at']} · "
                    f"{by_id[scan_id]['target']} · {by_id[scan_id]['total']} ports",
                ))
            if any(scan_id is None for scan_id in selected):
                st.caption("Select both reports to see their comparison.")
                return
            baseline, observation = [load_saved_report(scan_id) for scan_id in selected]
            st.caption(f"Earlier baseline: saved report #{selected[0]}. "
                       f"Later observation: saved report #{selected[1]}.")
        else:
            uploads = [st.file_uploader(
                label, type=["json"], max_upload_size=1, key=f"comparison_{role}_upload",
                help="Up to 1 MiB and 1,024 result rows per report. Uploading never starts a scan.",
            ) for role, label in (("baseline", "Earlier baseline JSON"), ("observation", "Later observation JSON"))]
            # Validate each provided upload even if its partner is still missing.
            reports = [read_uploaded_report(upload) if upload is not None else None for upload in uploads]
            if any(report is None for report in reports):
                st.caption("Upload both reports to see their comparison.")
                return
            baseline, observation = reports
        comparison = compare_reports(baseline, observation)
    except (HistoryError, ValueError) as exc:
        st.error(f"Comparison failed: {exc}")
        return

    st.caption(f"Matched target: {comparison['target']}. Service labels are conventional "
               "port assignments; a changed label does not identify a software change. "
               "Closed means an explicit connection refusal. Timeout/error outcomes remain uncertain.")
    metadata = []
    for role, label in (("baseline", "Earlier baseline"), ("observation", "Later observation")):
        report = comparison[role]
        metadata.append({"role": label, **{field: report[field] for field in (
            "target", "started_at", "finished_at", "duration_seconds", "timeout_seconds",
        )}, **report["summary"]})
    st.dataframe(metadata, hide_index=True)
    coverage = comparison["coverage"]
    st.caption(f"Coverage: {len(coverage['shared'])} shared ports · "
               f"{len(coverage['baseline_only'])} baseline only · "
               f"{len(coverage['observation_only'])} later only. "
               "Ports missing from either observation are not scanned.")
    for note in comparison["notes"]:
        st.warning(note)
    for column, key, label in zip(st.columns(4),
                                  ("status_changed", "status_unchanged", "not_scanned", "uncertain"),
                                  ("Status changed", "Status unchanged", "Missing coverage", "Uncertain outcomes")):
        column.metric(label, comparison["summary"][key])
    st.caption(f"Conventional service labels changed: {comparison['summary']['service_label_changed']}. "
               "Uncertain outcomes can also be changed, unchanged, or missing coverage; "
               "unchanged refers to status, not service labels or error text.")
    if comparison["results"]:
        st.dataframe(comparison["results"], hide_index=True)
    else:
        st.info("Neither report contains scanned ports.")
    st.download_button("Download comparison JSON", data=json.dumps(comparison, indent=2),
                       file_name="comparison.json", mime="application/json", on_click="ignore",
                       key="comparison_download")


def render_history():
    st.subheader("Local history")
    st.caption("Saving is explicit. Local history is unencrypted and may reveal service information.")
    try:
        entries = list_reports()
    except HistoryError as exc:
        st.error(str(exc))
        return
    notice = st.session_state.pop("history_notice", None)
    if notice:
        st.success(notice)
    if not entries:
        st.session_state.pop("pending_history_delete", None)
        st.caption("No saved reports yet. Use Save report on a scan or import to keep it after restart.")
        return
    st.dataframe(entries, hide_index=True)
    by_id = {entry["id"]: entry for entry in entries}
    if st.session_state.get("history_selected") not in by_id:
        st.session_state.pop("history_selected", None)
    selected = st.selectbox("Saved report", options=list(by_id), key="history_selected",
                            format_func=lambda scan_id: f"#{scan_id} · {by_id[scan_id]['started_at']} · "
                            f"{by_id[scan_id]['target']} · {by_id[scan_id]['total']} ports")
    if st.session_state.get("pending_history_delete") != selected:
        st.session_state.pop("pending_history_delete", None)
    try:
        report = load_saved_report(selected)
    except (HistoryError, ValueError) as exc:
        st.error(str(exc))
    else:
        render_report(report, source="history", scan_id=selected)
    if st.button("Delete selected report", key="history_delete"):
        st.session_state.pending_history_delete = selected
    if st.session_state.get("pending_history_delete") == selected:
        st.warning(f"Delete saved report #{selected}? This cannot be undone. Export it first if you need a copy.")
        if st.button(f"Confirm delete report #{selected}", key=f"history_confirm_delete_{selected}"):
            try:
                deleted = delete_report(selected)
            except HistoryError as exc:
                st.error(f"Delete failed: {exc}")
            else:
                st.session_state.pop("pending_history_delete", None)
                st.session_state.history_notice = (f"Deleted saved report #{selected}." if deleted
                                                   else f"Saved report #{selected} was already removed.")
                st.rerun()
        if st.button("Cancel deletion", key="history_cancel_delete"):
            st.session_state.pop("pending_history_delete", None)
            st.rerun()


st.set_page_config(page_title="NetScope", page_icon="🔐")
st.title("NetScope")
st.caption("Localhost TCP Port Scanner")
st.caption("Service labels are conventional port assignments, not detected software. "
           "Timeouts do not prove a port is closed.")

with st.form("scan"):
    target = st.text_input("Target", value="127.0.0.1")
    left, right = st.columns(2)
    start_port = left.number_input("Start port", min_value=1, max_value=65535,
                                   value=1, step=1, key="start_port")
    end_port = right.number_input("End port", min_value=1, max_value=65535,
                                  value=1024, step=1, key="end_port")
    timeout = st.number_input("Timeout per connection (seconds)",
                              min_value=MIN_TIMEOUT, max_value=MAX_TIMEOUT,
                              value=DEFAULT_TIMEOUT, step=0.05, key="timeout")
    st.caption(f"Only 127.0.0.1 and localhost are accepted. Scan at most {MAX_PORTS} "
               f"ports, with up to {MAX_WORKERS} concurrent connections per scan.")
    submitted = st.form_submit_button("Start Scan")

if submitted:
    # A failed new scan must not leave an older report looking like its result.
    st.session_state.pop("report", None)
    try:
        with st.spinner("Scanning..."):
            st.session_state.report = scan_target(
                target, start_port=start_port, end_port=end_port, timeout=timeout,
            )
        st.success("Scan completed")
    except ValueError as exc:
        st.error(str(exc))

if "report" in st.session_state:
    render_report(st.session_state.report)

st.subheader("Import a saved report")
uploaded = st.file_uploader("Choose a NetScope JSON report", type=["json"],
                             max_upload_size=1, key="report_upload",
                             help="Up to 1 MiB and 1,024 result rows. Importing never starts a scan.")
if uploaded is not None:
    try:
        imported_report = read_uploaded_report(uploaded)
    except ValueError as exc:
        st.error(f"Import failed: {exc}")
    else:
        render_report(imported_report, source="imported")

render_history()
render_comparison()
