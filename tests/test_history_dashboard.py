import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from history import HistoryError, list_reports, save_report
from reports import load_report
from dashboard_helpers import finish_scan


ROOT = Path(__file__).resolve().parents[1]


class HistoryDashboardTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "data" / "netscope.db"
        patcher = patch("history.DEFAULT_DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = (ROOT / "examples/localhost-open.json").read_bytes()

    def test_import_and_filter_alone_do_not_persist_then_explicit_save_deduplicates(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        with patch("scanner.scan_target") as scan, patch("scanner._scan_port_result") as probe:
            app.file_uploader[0].set_value(("report.json", self.data, "application/json")).run()
            app.checkbox(key="imported_only_open").check().run()
            self.assertFalse(self.db.exists())
            app.button(key="imported_save").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(list_reports()), 1)
            app.button(key="imported_save").click().run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(list_reports()), 1)
            scan.assert_not_called()
            probe.assert_not_called()

    def test_real_local_scan_save_restart_and_export(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            app.number_input(key="start_port").set_value(port)
            app.number_input(key="end_port").set_value(port)
            app.button[0].click().run()
            finish_scan(app)
        self.assertFalse(self.db.exists())
        expected = app.session_state["report"]
        app.button(key="scan_save").click().run()
        self.assertFalse(app.exception)
        with patch("scanner.scan_target") as scan, patch("scanner._scan_port_result") as probe, patch(
            "streamlit.download_button", wraps=st.download_button
        ) as download:
            restarted = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            self.assertFalse(restarted.exception)
            self.assertTrue(any(header.value.startswith("Saved report #") for header in restarted.subheader))
            self.assertEqual(json.loads(download.call_args.kwargs["data"]), expected)
            self.assertEqual(restarted.dataframe[-1].value["port"].tolist(), [port])
            scan.assert_not_called()
            probe.assert_not_called()

    def test_delete_requires_confirmation_and_only_removes_selected_report(self):
        first = save_report(load_report(self.data))
        second = save_report(load_report((ROOT / "examples/localhost-stopped.json").read_bytes()))
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        with patch("scanner.scan_target") as scan:
            app.selectbox(key="history_selected").set_value(first).run()
            app.button(key="history_delete").click().run()
            self.assertEqual(len(list_reports()), 2)
            self.assertTrue(any(f"#{first}" in warning.value for warning in app.warning))
            app.button(key="history_cancel_delete").click().run()
            self.assertEqual(len(list_reports()), 2)
            app.button(key="history_delete").click().run()
            app.button(key=f"history_confirm_delete_{first}").click().run()
            self.assertFalse(app.exception)
            self.assertEqual([entry["id"] for entry in list_reports()], [second])
            scan.assert_not_called()

    def test_selection_change_clears_stale_delete_confirmation(self):
        first = save_report(load_report(self.data))
        second = save_report(load_report((ROOT / "examples/localhost-stopped.json").read_bytes()))
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        app.button(key="history_delete").click().run()
        self.assertTrue(app.warning)
        app.selectbox(key="history_selected").set_value(first).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.warning)
        self.assertEqual({entry["id"] for entry in list_reports()}, {first, second})

    def test_failed_save_preserves_report_and_shows_error(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        app.file_uploader[0].set_value(("report.json", self.data, "application/json")).run()
        with patch("history.save_report", side_effect=HistoryError("History database is read-only.")):
            app.button(key="imported_save").click().run()
        self.assertFalse(app.exception)
        self.assertIn("Save failed", app.error[0].value)
        self.assertEqual(app.dataframe[0].value["port"].tolist(), [8080])
        self.assertFalse(self.db.exists())

    def test_failed_delete_preserves_history_and_confirmation(self):
        scan_id = save_report(load_report(self.data))
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        app.button(key="history_delete").click().run()
        with patch("history.delete_report", side_effect=HistoryError("History database is locked.")):
            app.button(key=f"history_confirm_delete_{scan_id}").click().run()
        self.assertFalse(app.exception)
        self.assertIn("Delete failed", app.error[0].value)
        self.assertEqual(len(list_reports()), 1)


if __name__ == "__main__":
    unittest.main()
