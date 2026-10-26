import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from reports import MAX_REPORT_BYTES
from dashboard_helpers import finish_scan


ROOT = Path(__file__).resolve().parents[1]


class ReportImportTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch("history.DEFAULT_DB_PATH", Path(directory.name) / "data" / "netscope.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = (ROOT / "examples" / "localhost-open.json").read_bytes()

    def test_real_upload_displays_imported_evidence_without_scanning(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        with patch("scanner.scan_target") as scan, patch("scanner._scan_port_result") as probe, patch(
            "streamlit.download_button", wraps=st.download_button
        ) as download:
            app.file_uploader[0].set_value(("legacy.json", self.data, "application/json")).run()
            self.assertFalse(app.exception)
            scan.assert_not_called()
            probe.assert_not_called()
            self.assertTrue(any(header.value == "Imported report" for header in app.subheader))
            self.assertFalse(any(header.value == "Latest scan" for header in app.subheader))
            self.assertTrue(any("not a new scan" in caption.value for caption in app.caption))
            self.assertEqual([metric.value for metric in app.metric], ["1", "0", "0", "0"])
            self.assertEqual(app.dataframe[0].value["port"].tolist(), [8080])
            arguments = download.call_args.kwargs
            self.assertEqual(arguments["file_name"], "imported-report.json")
            normalized = json.loads(arguments["data"])
            self.assertEqual(normalized, {"schema_version": 1, **json.loads(self.data)})
            app.checkbox(key="imported_only_open").check().run()
            self.assertFalse(app.exception)
            self.assertEqual(json.loads(download.call_args.kwargs["data"]), normalized)
            probe.assert_not_called()
            scan.assert_not_called()
            app.file_uploader[0].clear().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric), 0)
            self.assertEqual(len(app.get("download_button")), 0)

    def test_bad_upload_does_not_replace_live_report(self):
        with patch("scanner._scan_port_result", return_value={
            "port": 80, "service": "http", "status": "open",
        }):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            app.number_input(key="start_port").set_value(80)
            app.number_input(key="end_port").set_value(80)
            app.button[0].click().run()
            finish_scan(app)
        original = app.session_state["report"]
        with patch("scanner.scan_target") as scan, patch("scanner._scan_port_result") as probe:
            app.file_uploader[0].set_value(("broken.json", b"{}", "application/json")).run()
            self.assertFalse(app.exception)
            self.assertIn("Import failed", app.error[0].value)
            self.assertEqual(app.session_state["report"], original)
            self.assertEqual(app.dataframe[0].value["port"].tolist(), [80])
            self.assertEqual(len(app.get("download_button")), 2)
            scan.assert_not_called()
            probe.assert_not_called()

    def test_live_and_imported_controls_are_independent(self):
        with patch("scanner._scan_port_result", return_value={
            "port": 80, "service": "http", "status": "closed",
        }):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            app.number_input(key="start_port").set_value(80)
            app.number_input(key="end_port").set_value(80)
            app.button[0].click().run()
            finish_scan(app)
        with patch("scanner.scan_target") as scan:
            app.file_uploader[0].set_value(("legacy.json", self.data, "application/json")).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.checkbox), 2)
            self.assertEqual(len(app.get("download_button")), 4)
            app.checkbox(key="imported_only_open").check().run()
            self.assertFalse(app.checkbox(key="scan_only_open").value)
            self.assertEqual(app.dataframe[0].value["status"].tolist(), ["closed"])
            self.assertEqual(app.dataframe[1].value["status"].tolist(), ["open"])
            scan.assert_not_called()

    def test_empty_versioned_report_is_displayed_without_index_errors(self):
        report = json.loads(self.data)
        report.update(schema_version=1, results=[], open_ports=[],
                      summary={"total": 0, "open": 0, "closed": 0, "timeout": 0, "error": 0})
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        with patch("scanner._scan_port_result") as probe:
            app.file_uploader[0].set_value(("empty.json", json.dumps(report).encode(), "application/json")).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.info[0].value, "Report contains no port results.")
            self.assertEqual(len(app.get("download_button")), 2)
            probe.assert_not_called()

    def test_oversized_and_invalid_target_uploads_are_rejected(self):
        report = json.loads(self.data)
        report["target"] = "example.com"
        for data in (b" " * (MAX_REPORT_BYTES + 1), json.dumps(report).encode()):
            with self.subTest(size=len(data)), patch("scanner.scan_target") as scan, patch("scanner._scan_port_result") as probe:
                app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
                app.file_uploader[0].set_value(("bad.json", data, "application/json")).run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertEqual(len(app.metric), 0)
                self.assertEqual(len(app.get("download_button")), 0)
                scan.assert_not_called()
                probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
