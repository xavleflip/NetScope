import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class DashboardTests(unittest.TestCase):
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

            with patch("scanner.PORTS", [port]), patch(
                "streamlit.download_button", wraps=st.download_button
            ) as download:
                app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
                app.text_input[0].set_value("localhost")
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
        self.assertEqual(app.dataframe[0].value.to_dict("records"), report["open_ports"])

    def test_empty_open_port_table_still_downloads_unsuccessful_results(self):
        results = [
            {"port": 80, "service": "http", "status": "timeout"},
            {"port": 443, "service": "https", "status": "error", "error": "unavailable"},
        ]
        # Exercise real report assembly with controlled outcomes and no sockets.
        with patch("scanner.PORTS", [80, 443]), patch(
            "scanner._scan_port_result", side_effect=results
        ), patch("streamlit.download_button", wraps=st.download_button) as download:
            app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
            app.button[0].click().run()

        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "0")
        self.assertEqual(len(app.dataframe[0].value), 0)
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


if __name__ == "__main__":
    unittest.main()
