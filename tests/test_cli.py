from contextlib import redirect_stderr, redirect_stdout
import csv
from io import StringIO
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cli import main
from exports import serialize_report
from reports import load_report


ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scanner.py"
SHORT = ["--start-port", "1", "--end-port", "1", "--timeout", "0.05"]


class CLITests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def run_cli(self, *args, script=None):
        if script is None:
            command = [sys.executable, str(SCANNER), *args]
        else:
            prefix = "import sys\nsys.path.insert(0, sys.argv.pop(1))\n"
            command = [sys.executable, "-c", prefix + script, str(ROOT), *args]
        return subprocess.run(command, cwd=self.directory, capture_output=True, timeout=20)

    def test_help_and_invalid_commands_have_no_scan_output(self):
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        for text in (b"1024", b"32 concurrent", b"0.05-2", b"130", b"--overwrite", b"python scanner.py"):
            self.assertIn(text, help_result.stdout)
        self.assertEqual(help_result.stderr, b"")
        for args in (("--target", "example.com"), ("--target", "::1"),
                     ("--start-port", "1"), ("--end-port", "1"),
                     ("--start-port", "2", "--end-port", "1"),
                     ("--start-port", "1", "--end-port", "1025"),
                     ("--start-port", "0", "--end-port", "1"),
                     ("--timeout", "nan"), ("--timeout", "2.01"),
                     ("--format", "xml"), ("--overwrite",), ("--unknown",)):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"error:", result.stderr)
                self.assertNotIn(b"Progress:", result.stderr)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_invalid_arguments_and_help_never_open_sockets(self):
        with patch("scanner.socket.socket") as sockets, patch("scanner.socket.getaddrinfo") as dns:
            for args, code in ((["--target", "example.com"], 2), (["--help"], 0),
                               (["--timeout", "inf"], 2), (["--start-port", "65536", "--end-port", "65536"], 2)):
                with self.subTest(args=args), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as exited:
                        main(args)
                    self.assertEqual(exited.exception.code, code)
        sockets.assert_not_called()
        dns.assert_not_called()

    def test_real_listener_json_and_csv_subprocesses_match_validated_evidence(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(8)
            port = listener.getsockname()[1]
            options = ["--target", "localhost", "--start-port", str(port), "--end-port", str(port), "--timeout", "0.1"]
            json_path = self.directory / "scan café.json"
            json_result = self.run_cli(*options, "--output", str(json_path))
            csv_path = self.directory / "scan café.csv"
            csv_result = self.run_cli(*options, "--format", "csv", "--output", str(csv_path))
        self.assertEqual(json_result.returncode, 0, json_result.stderr)
        self.assertEqual(csv_result.returncode, 0, csv_result.stderr)
        report = load_report(json_result.stdout)
        self.assertEqual(report["scan_status"], "completed")
        self.assertEqual(report["requested_ports"], [port])
        self.assertEqual(report["results"][0]["status"], "open")
        self.assertEqual(json_path.read_bytes(), json_result.stdout)
        self.assertEqual(csv_path.read_bytes(), csv_result.stdout)
        self.assertNotIn(b"\r\r\n", csv_result.stdout)
        rows = list(csv.DictReader(StringIO(csv_result.stdout.decode("utf-8"), newline="")))
        expected = list(csv.DictReader(StringIO(serialize_report(report, "csv"), newline="")))[0]
        for field in ("target", "scan_status", "requested_count", "completed_count", "port", "service", "status", "error"):
            self.assertEqual(rows[0][field], expected[field])
        for result in (json_result, csv_result):
            self.assertIn(b"Progress:", result.stderr)
            self.assertIn(b"Scan completed:", result.stderr)
            self.assertNotIn(b"Progress:", result.stdout)
        self.assertFalse((self.directory / "data").exists())
        self.assertFalse((self.directory / "reports").exists())

    def test_no_options_keeps_original_ports_and_legacy_overwrite(self):
        first = self.run_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        report = load_report(first.stdout)
        self.assertEqual(report["requested_ports"], [21, 22, 25, 53, 80, 443, 3306, 8080])
        destination = self.directory / "reports" / "scan.json"
        self.assertEqual(destination.read_bytes(), first.stdout)
        destination.write_bytes(b"old report")
        second = self.run_cli()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(destination.read_bytes(), second.stdout)
        self.assertEqual(load_report(second.stdout)["summary"]["total"], 8)

    def test_explicit_collision_refuses_and_overwrite_requires_opt_in(self):
        destination = self.directory / "scan.json"
        destination.write_bytes(b"preserve this")
        refused = self.run_cli(*SHORT, "--output", str(destination))
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(refused.stdout, b"")
        self.assertIn(b"failed:", refused.stderr)
        self.assertEqual(destination.read_bytes(), b"preserve this")
        replaced = self.run_cli(*SHORT, "--output", str(destination), "--overwrite")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertEqual(destination.read_bytes(), replaced.stdout)
        load_report(replaced.stdout)
        self.assertEqual(list(self.directory.iterdir()), [destination])

    def test_missing_parent_and_subprocess_write_failure_leave_originals_intact(self):
        absent = self.run_cli(*SHORT, "--output", str(self.directory / "absent" / "report.json"))
        self.assertEqual(absent.returncode, 1)
        self.assertEqual(absent.stdout, b"")
        destination = self.directory / "report.json"
        destination.write_bytes(b"original")
        script = """from unittest.mock import patch
from cli import main
with patch('exports.os.replace', side_effect=OSError('controlled publish failure')):
    raise SystemExit(main())
"""
        result = self.run_cli(*SHORT, "--output", str(destination), "--overwrite", script=script)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"controlled publish failure", result.stderr)
        self.assertEqual(destination.read_bytes(), b"original")
        self.assertEqual(list(self.directory.iterdir()), [destination])

    def test_sigint_before_work_saves_cancelled_json_and_exits_130(self):
        script = """import signal
import scanner
from cli import main
real_scan = scanner.scan_target
def scan(*args, **kwargs):
    notify = kwargs['on_progress']
    def progress(completed, total):
        notify(completed, total)
        if completed == 0:
            signal.raise_signal(signal.SIGINT)
    kwargs['on_progress'] = progress
    return real_scan(*args, **kwargs)
scanner.scan_target = scan
raise SystemExit(main())
"""
        destination = self.directory / "partial.json"
        result = self.run_cli("--start-port", "1", "--end-port", "64", "--output", str(destination), script=script)
        self.assertEqual(result.returncode, 130, result.stderr)
        report = load_report(result.stdout)
        self.assertEqual(report["scan_status"], "cancelled")
        self.assertEqual(report["summary"]["total"], 0)
        self.assertEqual(len(report["requested_ports"]), 64)
        self.assertEqual(destination.read_bytes(), result.stdout)
        self.assertIn(b"Scan cancelled:", result.stderr)

    def test_sigint_during_probes_cooperatively_finishes_and_exports_cancelled_csv(self):
        script = """import signal
from threading import Event, Lock
from unittest.mock import patch
import scanner
from cli import main
real_scan = scanner.scan_target
def scan(*args, **kwargs):
    cancel = kwargs['cancel_event']
    signalled, lock = Event(), Lock()
    def probe(target, port, timeout):
        with lock:
            if not signalled.is_set():
                signalled.set()
                signal.raise_signal(signal.SIGINT)
        if not cancel.wait(10):
            raise RuntimeError('signal was not handled')
        return {'port': port, 'service': 'unknown', 'status': 'closed'}
    with patch('scanner._scan_port_result', side_effect=probe):
        return real_scan(*args, **kwargs)
scanner.scan_target = scan
raise SystemExit(main())
"""
        destination = self.directory / "partial.csv"
        result = self.run_cli("--start-port", "1", "--end-port", "64", "--format", "csv",
                              "--output", str(destination), script=script)
        self.assertEqual(result.returncode, 130, result.stderr)
        rows = list(csv.DictReader(StringIO(result.stdout.decode("utf-8"), newline="")))
        self.assertEqual(len(rows), 64)
        completed = int(rows[0]["completed_count"])
        self.assertGreaterEqual(completed, 1)
        self.assertLessEqual(completed, 32)
        self.assertEqual(sum(row["status"] == "closed" for row in rows), completed)
        self.assertTrue(all(row["scan_status"] == "cancelled" for row in rows))
        self.assertEqual(sum(row["status"] == "not scanned" for row in rows), 64 - completed)
        self.assertEqual(destination.read_bytes(), result.stdout)

    def test_recorded_connection_errors_are_successful_execution_and_signal_handler_is_restored(self):
        script = """import scanner
from cli import main
scanner._scan_port_result = lambda target, port, timeout: {
    'port': port, 'service': 'unknown', 'status': 'error', 'error': 'controlled socket error'}
raise SystemExit(main())
"""
        result = self.run_cli(*SHORT, script=script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(load_report(result.stdout)["summary"]["error"], 1)
        previous = signal.getsignal(signal.SIGINT)
        with redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as diagnostic, patch(
            "scanner.scan_target", side_effect=RuntimeError("worker failed")
        ):
            self.assertEqual(main(SHORT), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("worker failed", diagnostic.getvalue())
        self.assertIs(signal.getsignal(signal.SIGINT), previous)


if __name__ == "__main__":
    unittest.main()
