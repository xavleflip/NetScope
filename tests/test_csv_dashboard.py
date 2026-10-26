import csv
from io import StringIO
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard_helpers import finish_scan
from exports import serialize_report


ROOT = Path(__file__).resolve().parents[1]


class CSVDashboardTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "data" / "netscope.db"
        patcher = patch("history.DEFAULT_DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def payload(self, download, key):
        return [call.kwargs for call in download.call_args_list if call.kwargs.get("key") == key][-1]

    def test_filtered_import_and_history_csv_preserve_all_cancelled_evidence_and_safe_text(self):
        report = json.loads((ROOT / "examples/localhost-open.json").read_bytes())
        report.update(schema_version=2, scan_status="cancelled", requested_ports=[8080, 8081, 8082],
                      results=[{"port": 8080, "service": "=1+2", "status": "open"},
                               {"port": 8081, "service": "unknown", "status": "error", "error": "\t=1+2"}],
                      open_ports=[{"port": 8080, "service": "=1+2"}],
                      summary={"total": 2, "open": 1, "closed": 0, "timeout": 0, "error": 1})
        with patch("scanner.scan_target") as scan, patch("scanner._scan_port_result") as probe:
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            app.file_uploader(key="report_upload").set_value(("input.json", json.dumps(report).encode(), "application/json")).run()
            with patch("streamlit.download_button", wraps=st.download_button) as download:
                app.checkbox(key="imported_only_open").check().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.dataframe[0].value["port"].tolist(), [8080])
            csv_export = self.payload(download, "imported_csv_download")
            self.assertEqual(csv_export["file_name"], "imported-report-cancelled.csv")
            self.assertEqual(csv_export["mime"], "text/csv")
            self.assertEqual(csv_export["on_click"], "ignore")
            rows = list(csv.DictReader(StringIO(csv_export["data"], newline="")))
            self.assertEqual([row["status"] for row in rows], ["open", "error", "not scanned"])
            self.assertEqual(rows[0]["service"], "'=1+2")
            self.assertEqual(rows[1]["error"], "'\t=1+2")
            self.assertTrue(all(row["scan_status"] == "cancelled" for row in rows))
            self.assertEqual(json.loads(self.payload(download, "imported_download")["data"]), report)
            self.assertFalse(self.db.exists())
            with patch("streamlit.download_button", wraps=st.download_button) as download:
                app.button(key="imported_save").click().run()
            self.assertFalse(app.exception)
            saved = self.payload(download, "history_csv_download")
            self.assertIn("cancelled.csv", saved["file_name"])
            self.assertEqual(saved["data"], csv_export["data"])
            scan.assert_not_called()
            probe.assert_not_called()

    def test_live_local_scan_csv_and_json_use_the_shared_full_report_export(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            app.number_input(key="start_port").set_value(port)
            app.number_input(key="end_port").set_value(port)
            app.button[0].click().run()
            finish_scan(app)
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            app.checkbox(key="scan_only_open").check().run()
        self.assertFalse(app.exception)
        report = app.session_state["report"]
        self.assertEqual(self.payload(download, "scan_csv_download")["data"], serialize_report(report, "csv"))
        self.assertEqual(json.loads(self.payload(download, "scan_download")["data"]), report)
        rows = list(csv.DictReader(StringIO(self.payload(download, "scan_csv_download")["data"], newline="")))
        self.assertEqual(rows[0]["port"], str(port))
        self.assertEqual(rows[0]["status"], "open")
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
