from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from exports import CSV_COLUMNS, serialize_report, write_report
from reports import load_report


ROOT = Path(__file__).resolve().parents[1]


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.report = load_report((ROOT / "examples/localhost-open.json").read_bytes())

    def csv_rows(self, report):
        return list(csv.DictReader(StringIO(serialize_report(report, "csv"), newline="")))

    def test_json_matches_validated_evidence_without_input_mutation_or_io(self):
        report = deepcopy(self.report)
        report["results"][0]["service"] = report["open_ports"][0]["service"] = "=formula café"
        original = deepcopy(report)
        with patch("socket.socket") as sockets, patch("builtins.open") as files:
            text = serialize_report(report)
        self.assertEqual(json.loads(text), original)
        self.assertEqual(report, original)
        self.assertIn("café", text)
        sockets.assert_not_called()
        files.assert_not_called()

    def test_csv_has_stable_columns_and_all_completed_outcomes(self):
        report = deepcopy(self.report)
        report["results"] = [
            {"port": 80, "service": "http", "status": "open"},
            {"port": 81, "service": "unknown", "status": "closed"},
            {"port": 82, "service": "unknown", "status": "timeout"},
            {"port": 83, "service": "unknown", "status": "error", "error": 'failed, "quoted"\nnext line'},
        ]
        report["open_ports"] = [{"port": 80, "service": "http"}]
        report["summary"] = {"total": 4, "open": 1, "closed": 1, "timeout": 1, "error": 1}
        reader = csv.DictReader(StringIO(serialize_report(report, "csv"), newline=""))
        self.assertEqual(tuple(reader.fieldnames), CSV_COLUMNS)
        rows = list(reader)
        self.assertEqual([row["status"] for row in rows], ["open", "closed", "timeout", "error"])
        self.assertEqual(rows[-1]["error"], report["results"][-1]["error"])
        self.assertTrue(all(row["target"] == "127.0.0.1" and row["scan_status"] == "completed" for row in rows))
        self.assertTrue(all(row["requested_count"] == "4" and row["completed_count"] == "4" for row in rows))

    def test_formula_prefixes_and_hidden_leading_characters_become_literal(self):
        values = ("=SUM(1,2)", "+cmd", "-1+2", "@SUM(A1)", "  =formula", "\tplain",
                  "\rplain", "\nplain", "\x00=formula", "\u200b=formula", "\ufeff+cmd", "\u00a0@cmd")
        for value in values:
            with self.subTest(value=repr(value)):
                report = deepcopy(self.report)
                report["results"] = [{"port": 80, "service": value, "status": "error", "error": value}]
                report["open_ports"] = []
                report["summary"] = {"total": 1, "open": 0, "closed": 0, "timeout": 0, "error": 1}
                original = deepcopy(report)
                row = self.csv_rows(report)[0]
                self.assertEqual(row["service"], "'" + value)
                self.assertEqual(row["error"], "'" + value)
                self.assertEqual(json.loads(serialize_report(report))["results"][0]["service"], value)
                self.assertEqual(report, original)

    def test_csv_quoting_unicode_and_benign_text_are_preserved(self):
        for value in ('service, "name"\nline', "café 服务", " ordinary text", "'literal", "http"):
            with self.subTest(value=value):
                report = deepcopy(self.report)
                report["results"][0]["service"] = report["open_ports"][0]["service"] = value
                self.assertEqual(self.csv_rows(report)[0]["service"], value)

    def test_cancelled_rows_include_requested_but_unscanned_ports(self):
        report = {**self.report, "schema_version": 2, "scan_status": "cancelled", "requested_ports": [9000, 8080]}
        rows = self.csv_rows(report)
        self.assertEqual([row["port"] for row in rows], ["9000", "8080"])
        self.assertEqual([row["status"] for row in rows], ["not scanned", "open"])
        self.assertTrue(all(row["scan_status"] == "cancelled" for row in rows))
        self.assertTrue(all(row["requested_count"] == "2" and row["completed_count"] == "1" for row in rows))
        self.assertEqual(rows[0]["service"], "")

    def test_empty_report_retains_completion_metadata(self):
        for status in ("completed", "cancelled"):
            report = {**self.report, "schema_version": 2, "scan_status": status, "requested_ports": [],
                      "results": [], "open_ports": [],
                      "summary": {"total": 0, "open": 0, "closed": 0, "timeout": 0, "error": 0}}
            rows = self.csv_rows(report)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["scan_status"], status)
            self.assertEqual(rows[0]["port"], "")
            self.assertEqual(rows[0]["status"], "")

    def test_invalid_report_or_format_is_rejected_before_export(self):
        with self.assertRaises(ValueError):
            serialize_report({}, "csv")
        with self.assertRaises(ValueError):
            serialize_report(self.report, "xml")

    def test_atomic_utf8_write_collision_and_explicit_overwrite(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.csv"
            text = 'café,"quoted"\r\n'
            write_report(path, text)
            self.assertEqual(path.read_bytes(), text.encode("utf-8"))
            with self.assertRaises(FileExistsError):
                write_report(path, "replacement")
            self.assertEqual(path.read_bytes(), text.encode("utf-8"))
            write_report(path, "replacement", overwrite=True)
            self.assertEqual(path.read_text(), "replacement")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_concurrent_create_has_one_complete_winner(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            barrier = Barrier(4)
            payloads = [str(index) * 100000 for index in range(4)]

            def write(text):
                barrier.wait(10)
                try:
                    write_report(path, text)
                    return True
                except FileExistsError:
                    return False

            with ThreadPoolExecutor(max_workers=4) as pool:
                successes = list(pool.map(write, payloads))
            self.assertEqual(sum(successes), 1)
            self.assertIn(path.read_text(), payloads)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_write_or_publish_failure_preserves_existing_file_and_cleans_temporary(self):
        for boundary in ("exports.os.fsync", "exports.os.replace"):
            with self.subTest(boundary=boundary), TemporaryDirectory() as directory:
                path = Path(directory) / "report.json"
                path.write_bytes(b"keep original")
                with patch(boundary, side_effect=OSError("controlled write failure")):
                    with self.assertRaises(OSError):
                        write_report(path, "new content", overwrite=True)
                self.assertEqual(path.read_bytes(), b"keep original")
                self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_create_publish_failure_and_missing_parent_leave_no_output(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch("exports.os.link", side_effect=OSError("filesystem cannot link")):
                with self.assertRaises(OSError):
                    write_report(path, "content")
            self.assertEqual(list(Path(directory).iterdir()), [])
            with self.assertRaises(OSError):
                write_report(Path(directory) / "absent" / "report.json", "content")
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
