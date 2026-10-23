
import streamlit as st
from scanner import scan_target

st.set_page_config(
    page_title="NetScope",
    page_icon="🔐"
)

st.title("NetScope")
st.caption("Local Network Security Scanner")

target = st.text_input(
    "Target",
    value="127.0.0.1"
)

if st.button("Start Scan"):
    with st.spinner("Scanning..."):
        try:
            result = scan_target(target)
            ports = result["open_ports"]

            st.success("Scan completed")
            st.metric("Open Ports", len(ports))
            st.dataframe(ports)
            st.download_button(
                "Download JSON Report",
                data=__import__("json").dumps(
                    result, indent=2
                ),
                file_name="scan.json",
                mime="application/json"
            )
        except ValueError as e:
            st.error(str(e))
