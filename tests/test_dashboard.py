import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from scanner import scan_target


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class DashboardTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch("history.DEFAULT_DB_PATH", Path(directory.name) / "data" / "netscope.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_initial_screen_does_not_scan(self):
        with patch("scanner.scan_target") as scan:
            app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

        self.assertFalse(app.exception)
        scan.assert_not_called()
        self.assertEqual(app.text_input[0].value, "127.0.0.1")
        self.assertEqual(app.button[0].label, "Start Scan")
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(len(app.get("download_button")), 0)

    def test_local_scan_displays_open_port_and_downloads_full_report(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]

            with patch(
                "streamlit.download_button", wraps=st.download_button
            ) as download:
                app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
                app.text_input[0].set_value("localhost")
                app.number_input(key="start_port").set_value(port)
                app.number_input(key="end_port").set_value(port)
                app.number_input(key="timeout").set_value(0.1)
                app.button[0].click().run()

        self.assertFalse(app.exception)
        self.assertEqual(app.success[0].value, "Scan completed")
        self.assertEqual(app.metric[0].value, "1")
        self.assertEqual(len(app.get("download_button")), 1)
        download.assert_called_once()
        arguments = download.call_args.kwargs
        self.assertEqual(arguments["file_name"], "scan.json")
        self.assertEqual(arguments["mime"], "application/json")
        report = json.loads(arguments["data"])
        self.assertEqual(report["target"], "localhost")
        self.assertEqual(report["summary"], {
            "total": 1, "open": 1, "closed": 0, "timeout": 0, "error": 0,
        })
        self.assertEqual(report["results"][0]["status"], "open")
        self.assertEqual(report["results"][0]["port"], port)
        self.assertEqual(report["timeout_seconds"], 0.1)
        self.assertEqual(app.dataframe[0].value.to_dict("records"), report["results"])

    def test_empty_open_port_table_still_downloads_unsuccessful_results(self):
        results = [
            {"port": 80, "service": "http", "status": "timeout"},
            {"port": 81, "service": "unknown", "status": "error", "error": "unavailable"},
        ]
        # Exercise real report assembly with controlled outcomes and no sockets.
        by_port = {row["port"]: row for row in results}
        with patch("scanner._scan_port_result", side_effect=lambda target, port, timeout: by_port[port]) as probe, patch(
            "streamlit.download_button", wraps=st.download_button
        ) as download:
            app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
            app.number_input(key="start_port").set_value(80)
            app.number_input(key="end_port").set_value(81)
            app.button[0].click().run()
            self.assertEqual(len(app.dataframe[0].value), 2)
            download.reset_mock()
            app.checkbox[0].check().run()
            self.assertEqual(probe.call_count, 2)

        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "0")
        self.assertEqual(len(app.dataframe), 0)
        self.assertEqual(app.info[0].value, "No open ports found in this scan.")
        self.assertEqual(len(app.get("download_button")), 1)
        download.assert_called_once()
        report = json.loads(download.call_args.kwargs["data"])
        self.assertEqual(report["open_ports"], [])
        self.assertEqual(report["results"], results)
        self.assertEqual(report["summary"], {
            "total": 2, "open": 0, "closed": 0, "timeout": 1, "error": 1,
        })

    def test_rejected_target_shows_error_without_probing_or_download(self):
        with patch("scanner._scan_port_result") as probe:
            app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
            app.text_input[0].set_value("192.0.2.1")
            app.button[0].click().run()

        self.assertFalse(app.exception)
        probe.assert_not_called()
        self.assertEqual(app.error[0].value, "Localhost scanning only")
        self.assertEqual(len(app.success), 0)
        self.assertEqual(len(app.metric), 0)
        self.assertEqual(len(app.get("download_button")), 0)

    def test_filter_and_reruns_keep_report_without_rescanning(self):
        results = [
            {"port": 80, "service": "http", "status": "open"},
            {"port": 81, "service": "unknown", "status": "closed"},
            {"port": 82, "service": "unknown", "status": "timeout"},
            {"port": 83, "service": "unknown", "status": "error", "error": "failed"},
        ]
        by_port = {row["port"]: row for row in results}
        with patch("scanner._scan_port_result", side_effect=lambda target, port, timeout: by_port[port]), patch(
            "scanner.scan_target", wraps=scan_target
        ) as scan, patch("streamlit.download_button", wraps=st.download_button) as download:
            app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
            app.number_input(key="start_port").set_value(80)
            app.number_input(key="end_port").set_value(83)
            app.button[0].click().run()
            self.assertFalse(app.exception)
            report = json.loads(download.call_args.kwargs["data"])
            self.assertEqual([metric.value for metric in app.metric], ["1", "1", "1", "1"])
            self.assertEqual(app.dataframe[0].value["port"].tolist(), [80, 81, 82, 83])

            app.checkbox[0].check().run()
            self.assertEqual(app.dataframe[0].value["port"].tolist(), [80])
            self.assertEqual(json.loads(download.call_args.kwargs["data"]), report)
            app.checkbox[0].uncheck().run()
            app.run()
            # Editing the form also must not replace the saved report until submission.
            app.text_input[0].set_value("localhost").run()
            self.assertFalse(app.exception)
            scan.assert_called_once_with("127.0.0.1", start_port=80, end_port=83, timeout=0.5)
            self.assertEqual(app.dataframe[0].value["port"].tolist(), [80, 81, 82, 83])
            self.assertEqual(json.loads(download.call_args.kwargs["data"]), report)
            self.assertTrue(any("Target: 127.0.0.1" in caption.value for caption in app.caption))

    def test_invalid_new_scan_clears_previous_report(self):
        with patch("scanner._scan_port_result", return_value={
            "port": 80, "service": "http", "status": "open",
        }) as probe:
            app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
            app.number_input(key="start_port").set_value(80)
            app.number_input(key="end_port").set_value(80)
            app.button[0].click().run()
            self.assertEqual(len(app.get("download_button")), 1)
            app.number_input(key="end_port").set_value(79)
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertIn("Start port", app.error[0].value)
            probe.assert_called_once()
            self.assertEqual(len(app.metric), 0)
            self.assertEqual(len(app.dataframe), 0)
            self.assertEqual(len(app.get("download_button")), 0)
            with self.assertRaises(KeyError):
                app.session_state["report"]

    def test_oversized_range_is_rejected_without_probes(self):
        with patch("scanner._scan_port_result") as probe:
            app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
            app.number_input(key="start_port").set_value(1)
            app.number_input(key="end_port").set_value(1025)
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertIn("1024", app.error[0].value)
            probe.assert_not_called()
            self.assertEqual(len(app.get("download_button")), 0)


if __name__ == "__main__":
    unittest.main()
