from contextlib import chdir, redirect_stdout
from datetime import datetime, timedelta
import errno
from io import StringIO
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from scanner import scan_port, scan_target


class ScanResultTests(unittest.TestCase):
    def test_connection_outcomes_and_cleanup(self):
        cases = (
            (None, "open"),
            (ConnectionRefusedError("refused"), "closed"),
            (OSError(errno.ECONNREFUSED, "refused"), "closed"),
            (OSError(10061, "Windows refusal"), "closed"),
            (TimeoutError("timed out"), "timeout"),
            (OSError(errno.ETIMEDOUT, "timed out"), "timeout"),
            (OSError(10060, "Windows timeout"), "timeout"),
            (OSError(errno.EHOSTUNREACH, "unreachable"), "error"),
            (PermissionError("denied"), "error"),
            (OSError("unspecified socket failure"), "error"),
        )
        for error, status in cases:
            with self.subTest(error=error), patch("scanner.PORTS", [443]), patch(
                "scanner.socket.socket"
            ) as factory, patch("scanner.socket.getservbyport", return_value="https"):
                connection = factory.return_value.__enter__.return_value
                connection.connect.side_effect = error
                report = scan_target()
                row = report["results"][0]
                self.assertEqual(row["status"], status)
                self.assertEqual((row["port"], row["service"]), (443, "https"))
                self.assertEqual(report["summary"][status], 1)
                self.assertEqual(len(report["open_ports"]), int(status == "open"))
                if status == "error":
                    self.assertEqual(row["error"], str(error))
                connection.settimeout.assert_called_once_with(0.5)
                connection.connect.assert_called_once_with(("127.0.0.1", 443))
                factory.return_value.__exit__.assert_called_once()

    def test_windows_error_attribute(self):
        for code, status in ((10061, "closed"), (10060, "timeout"), (10065, "error")):
            with self.subTest(code=code), patch("scanner.PORTS", [80]), patch(
                "scanner.socket.socket"
            ) as factory:
                error = OSError("Windows socket failure")
                error.winerror = code
                factory.return_value.__enter__.return_value.connect.side_effect = error
                self.assertEqual(scan_target()["results"][0]["status"], status)

    def test_report_consistency_json_and_monotonic_duration(self):
        with patch("scanner.PORTS", [21, 22, 25, 53]), patch("scanner.socket.socket") as factory, patch(
            "scanner.socket.getservbyport", return_value="test-service"
        ), patch("scanner.time.perf_counter", side_effect=[100.0, 101.25]):
            # Workers may start in any order; tie each outcome to its port.
            outcomes = {21: None, 22: ConnectionRefusedError("refused"),
                        25: TimeoutError("slow"), 53: OSError("failed")}
            def connect(address):
                error = outcomes[address[1]]
                if error is not None:
                    raise error
            factory.return_value.__enter__.return_value.connect.side_effect = connect
            report = scan_target("localhost")
        self.assertEqual(report["summary"], {
            "total": 4, "open": 1, "closed": 1, "timeout": 1, "error": 1
        })
        self.assertEqual(sum(report["summary"][s] for s in ("open", "closed", "timeout", "error")), 4)
        self.assertEqual([row["port"] for row in report["results"]], [21, 22, 25, 53])
        self.assertEqual(report["open_ports"], [{"port": 21, "service": "test-service"}])
        self.assertEqual(report["duration_seconds"], 1.25)
        self.assertEqual(report["timestamp"], report["started_at"])
        started = datetime.fromisoformat(report["started_at"])
        finished = datetime.fromisoformat(report["finished_at"])
        self.assertEqual(started.utcoffset(), timedelta(0))
        self.assertEqual(finished.utcoffset(), timedelta(0))
        self.assertGreaterEqual(finished, started)
        self.assertEqual(json.loads(json.dumps(report)), report)

    def test_unknown_service_does_not_change_connection_status(self):
        with patch("scanner.PORTS", [65535]), patch("scanner.socket.socket"), patch(
            "scanner.socket.getservbyport", side_effect=OSError("no assignment")
        ):
            report = scan_target()
        self.assertEqual(report["results"], [{"port": 65535, "service": "unknown", "status": "open"}])

    def test_socket_creation_failure_is_reported(self):
        with patch("scanner.PORTS", [80]), patch("scanner.socket.socket", side_effect=OSError("no sockets")):
            report = scan_target()
        self.assertEqual(report["results"][0]["status"], "error")
        self.assertEqual(report["results"][0]["error"], "no sockets")

    def test_empty_port_list_produces_consistent_report(self):
        with patch("scanner.PORTS", []), patch("scanner.socket.socket") as factory:
            report = scan_target()
        factory.assert_not_called()
        self.assertEqual(report["results"], [])
        self.assertEqual(report["open_ports"], [])
        self.assertEqual(report["summary"], {"total": 0, "open": 0, "closed": 0, "timeout": 0, "error": 0})

    def test_boolean_helper_compatibility(self):
        for error, expected in ((None, True), (TimeoutError("slow"), False),
                                (ConnectionRefusedError("refused"), False), (OSError("failed"), False)):
            with self.subTest(error=error), patch("scanner.socket.socket") as factory:
                factory.return_value.__enter__.return_value.connect.side_effect = error
                self.assertIs(scan_port("localhost", 80), expected)

    def test_command_line_stdout_matches_saved_json(self):
        scanner_path = Path(__file__).resolve().parents[1] / "scanner.py"
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory, chdir(directory), redirect_stdout(output), patch(
            "socket.socket"
        ) as factory, patch("socket.getservbyport", return_value="test-service"):
            factory.return_value.__enter__.return_value.connect.side_effect = TimeoutError("slow")
            runpy.run_path(str(scanner_path), run_name="__main__")
            saved = json.loads(Path("reports/scan.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(output.getvalue()), saved)
        self.assertEqual(saved["summary"]["timeout"], 8)
        self.assertEqual(len(saved["results"]), 8)
        self.assertEqual(saved["open_ports"], [])


if __name__ == "__main__":
    unittest.main()
