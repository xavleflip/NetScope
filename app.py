
import json

import streamlit as st

from scanner import DEFAULT_TIMEOUT, MAX_PORTS, MAX_TIMEOUT, MAX_WORKERS, MIN_TIMEOUT, scan_target
from reports import MAX_REPORT_BYTES, load_report


def render_report(report, *, imported=False):
    """Render live and imported evidence with independent controls and downloads."""
    prefix = "imported" if imported else "scan"
    st.subheader("Imported report" if imported else "Latest scan")
    if imported:
        st.caption("Imported observation, not a new scan. Validation checks format and "
                   "consistency, not the authenticity of the measurements.")
    st.caption(f"Target: {report['target']} · Ports checked: {report['summary']['total']} · "
               f"Started: {report['started_at']} · "
               f"Timeout: {report['timeout_seconds']:g}s · "
               f"Duration: {report['duration_seconds']:.3f}s")
    for column, status in zip(st.columns(4), ("open", "closed", "timeout", "error")):
        column.metric("Open Ports" if status == "open" else status.title(),
                      report["summary"][status])
    only_open = st.checkbox("Show only open ports", key=f"{prefix}_only_open")
    rows = [row for row in report["results"] if not only_open or row["status"] == "open"]
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.info("No open ports found in this scan." if only_open else "Report contains no port results.")
    st.download_button("Download imported JSON report" if imported else "Download JSON Report",
                       data=json.dumps(report, indent=2),
                       file_name="imported-report.json" if imported else "scan.json",
                       mime="application/json", on_click="ignore", key=f"{prefix}_download")


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
        render_report(imported_report, imported=True)
