
import json

import streamlit as st

from scanner import DEFAULT_TIMEOUT, MAX_PORTS, MAX_TIMEOUT, MAX_WORKERS, MIN_TIMEOUT, scan_target
from reports import MAX_REPORT_BYTES, load_report
from history import HistoryError, delete_report, list_reports, load_saved_report, save_report


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
        uploaded.seek(0)
        imported_report = load_report(uploaded.read(MAX_REPORT_BYTES + 1))
    except ValueError as exc:
        st.error(f"Import failed: {exc}")
    else:
        render_report(imported_report, source="imported")

render_history()
