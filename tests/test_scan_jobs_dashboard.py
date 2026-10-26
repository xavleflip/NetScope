import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.errors import AppTestError

from dashboard_helpers import finish_scan
from history import list_reports, load_saved_report


ROOT = Path(__file__).resolve().parents[1]


class ScanJobDashboardTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "data" / "netscope.db"
        patcher = patch("history.DEFAULT_DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def app(self, start, end):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        app.number_input(key="start_port").set_value(start)
        app.number_input(key="end_port").set_value(end)
        app.number_input(key="timeout").set_value(0.05)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        return app

    def test_cancel_controls_block_resubmission_until_cleanup_then_export_and_save(self):
        saturated, release = Event(), Event()
        lock = Lock()
        seen = []

        def probe(target, port, timeout):
            with lock:
                seen.append(port)
                if len(seen) == 32:
                    saturated.set()
            if not release.wait(10):
                raise AssertionError("Test did not release probes")
            return {"port": port, "service": "unknown", "status": "closed"}

        with patch("scanner._scan_port_result", side_effect=probe):
            app = self.app(1, 64)
            job = app.session_state["scan_job"]
            try:
                self.assertTrue(saturated.wait(10))
                app.run()
                self.assertTrue(app.button[0].disabled)
                self.assertIn("0/64", app.get("progress")[0].proto.text)
                self.assertFalse(app.button(key=f"cancel_scan_{job.run_id}").disabled)
                with self.assertRaises(AppTestError):
                    app.button[0].click()
                app.run()
                self.assertIs(app.session_state["scan_job"], job)
                app.button(key=f"cancel_scan_{job.run_id}").click().run()
                self.assertTrue(job.cancel_event.is_set())
                self.assertTrue(job.active)
                self.assertTrue(app.button[0].disabled)
                self.assertTrue(app.button(key=f"cancel_scan_{job.run_id}").disabled)
                self.assertIn("Cancelling", app.get("progress")[0].proto.text)
                self.assertFalse(app.get("download_button"))
            finally:
                release.set()
                self.assertTrue(job.join(10))
            with patch("streamlit.download_button", wraps=st.download_button) as download:
                app.run()
        self.assertFalse(app.exception)
        report = app.session_state["report"]
        self.assertEqual(report["scan_status"], "cancelled")
        self.assertEqual(report["summary"]["total"], 32)
        self.assertEqual(len(report["requested_ports"]), 64)
        self.assertEqual(len(seen), 32)
        self.assertTrue(any("32 ports not scanned" in warning.value for warning in app.warning))
        self.assertFalse(any(success.value == "Scan completed" for success in app.success))
        self.assertFalse(app.button[0].disabled)
        self.assertEqual(download.call_args.kwargs["file_name"], "scan-cancelled.json")
        self.assertEqual(json.loads(download.call_args.kwargs["data"]), report)
        self.assertEqual(app.button(key="scan_save").label, "Save cancelled report")
        self.assertFalse(self.db.exists())
        app.button(key="scan_save").click().run()
        self.assertFalse(app.exception)
        saved_id = list_reports()[0]["id"]
        self.assertEqual(load_saved_report(saved_id), report)
        self.assertTrue(any(header.value.endswith("(cancelled)") for header in app.subheader))

    def test_partial_progress_uses_active_request_and_preserves_submitted_form(self):
        blocked, release = Event(), Event()

        def probe(target, port, timeout):
            if port == 81:
                blocked.set()
                if not release.wait(10):
                    raise AssertionError("Test did not release probe")
            return {"port": port, "service": "unknown", "status": "open"}

        with patch("scanner._scan_port_result", side_effect=probe):
            app = self.app(80, 81)
            job = app.session_state["scan_job"]
            try:
                self.assertTrue(blocked.wait(10))
                messages = []
                while True:
                    message = job.messages.get(timeout=10)
                    messages.append(message)
                    if message[1] == "progress" and message[2] == (1, 2):
                        break
                for message in messages:
                    job.messages.put(message)
                app.number_input(key="end_port").set_value(90).run()
                self.assertIn("1/2", app.get("progress")[0].proto.text)
                self.assertEqual(app.get("progress")[0].proto.value, 50)
                self.assertTrue(app.button[0].disabled)
            finally:
                release.set()
                self.assertTrue(job.join(10))
            app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["report"]["requested_ports"], [80, 81])
        self.assertEqual(app.number_input(key="start_port").value, 80)
        self.assertEqual(app.number_input(key="end_port").value, 81)
        self.assertTrue(any(success.value == "Scan completed" for success in app.success))

    def test_two_dashboard_sessions_do_not_cancel_or_replace_each_others_jobs(self):
        release = Event()
        starts = {80: Event(), 81: Event()}

        def probe(target, port, timeout):
            starts[port].set()
            if not release.wait(10):
                raise AssertionError("Test did not release sessions")
            return {"port": port, "service": "unknown", "status": "open"}

        with patch("scanner._scan_port_result", side_effect=probe):
            first = self.app(80, 80)
            second = self.app(81, 81)
            first_job, second_job = first.session_state["scan_job"], second.session_state["scan_job"]
            try:
                self.assertTrue(starts[80].wait(10))
                self.assertTrue(starts[81].wait(10))
                first.button(key=f"cancel_scan_{first_job.run_id}").click().run()
                second.run()
                self.assertTrue(first_job.cancel_event.is_set())
                self.assertFalse(second_job.cancel_event.is_set())
                self.assertIs(second.session_state["scan_job"], second_job)
            finally:
                release.set()
                self.assertTrue(first_job.join(10))
                self.assertTrue(second_job.join(10))
            first.run()
            second.run()
        self.assertFalse(first.exception)
        self.assertFalse(second.exception)
        self.assertEqual(first.session_state["report"]["scan_status"], "cancelled")
        self.assertEqual(second.session_state["report"]["scan_status"], "completed")
        self.assertEqual(second.session_state["report"]["requested_ports"], [81])

    def test_unexpected_job_failure_clears_old_result_and_allows_recovery(self):
        with patch("scanner._scan_port_result", side_effect=RuntimeError("controlled failure")):
            app = self.app(80, 80)
            finish_scan(app)
        self.assertFalse(app.exception)
        self.assertTrue(any("controlled failure" in error.value for error in app.error))
        self.assertFalse(app.get("download_button"))
        self.assertNotIn("report", app.session_state)
        self.assertFalse(app.button[0].disabled)
        with patch("scanner._scan_port_result", return_value={"port": 80, "service": "http", "status": "open"}):
            app.button[0].click().run()
            finish_scan(app)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.session_state["report"]["scan_status"], "completed")

    def test_job_thread_start_failure_is_visible_without_a_stuck_session(self):
        with patch("jobs.Thread") as thread, patch(
            "scanner._scan_port_result"
        ) as probe:
            thread.return_value.start.side_effect = RuntimeError("cannot start thread")
            app = self.app(80, 80)
        self.assertTrue(any("cannot start thread" in error.value for error in app.error))
        self.assertNotIn("scan_job", app.session_state)
        self.assertFalse(app.button[0].disabled)
        probe.assert_not_called()

    def test_imported_cancelled_report_is_labelled_saved_and_compared_without_scanning(self):
        before = (ROOT / "examples/localhost-open.json").read_bytes()
        partial = json.loads((ROOT / "examples/localhost-stopped.json").read_bytes())
        partial.update(schema_version=2, scan_status="cancelled", requested_ports=[8080, 9000],
                       results=[], open_ports=[], summary={"total": 0, "open": 0, "closed": 0, "timeout": 0, "error": 0})
        data = json.dumps(partial).encode()
        with patch("scanner.scan_target") as scan, patch("scanner._scan_port_result") as probe:
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
            with patch("streamlit.download_button", wraps=st.download_button) as download:
                app.file_uploader(key="report_upload").set_value(("partial.json", data, "application/json")).run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Cancelled scan: 0/2" in warning.value for warning in app.warning))
            self.assertEqual(download.call_args.kwargs["file_name"], "imported-report-cancelled.json")
            self.assertEqual(app.button(key="imported_save").label, "Save cancelled report")
            app.button(key="imported_save").click().run()
            self.assertEqual(load_saved_report(list_reports()[0]["id"]), partial)
            app.radio(key="comparison_source").set_value("JSON files").run()
            app.file_uploader(key="comparison_baseline_upload").set_value(("before.json", before, "application/json"))
            app.file_uploader(key="comparison_observation_upload").set_value(("partial.json", data, "application/json")).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.dataframe[-1].value["after_status"].tolist(), ["not scanned", "not scanned"])
            self.assertEqual(app.dataframe[-2].value["scan_status"].tolist(), ["completed", "cancelled"])
            self.assertTrue(any("Cancelled scan included" in warning.value for warning in app.warning))
            scan.assert_not_called()
            probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
