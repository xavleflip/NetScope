from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from comparison import compare_reports
from history import list_reports, load_saved_report, save_report
from reports import load_report, scan_details, validate_report


ROOT = Path(__file__).resolve().parents[1]


class PartialReportTests(unittest.TestCase):
    def setUp(self):
        self.legacy = load_report((ROOT / "examples/localhost-open.json").read_bytes())
        self.complete = {**deepcopy(self.legacy), "schema_version": 2,
                         "scan_status": "completed", "requested_ports": [8080]}
        self.partial = {**deepcopy(self.complete), "scan_status": "cancelled", "requested_ports": [8080, 9000]}

    def test_legacy_remains_version_one_and_is_treated_as_completed(self):
        for report in (self.legacy, {key: value for key, value in self.legacy.items() if key != "schema_version"}):
            normalized = validate_report(report)
            self.assertEqual(normalized, self.legacy)
            self.assertEqual(scan_details(normalized), {"scan_status": "completed", "requested_ports": [8080]})
            self.assertNotIn("scan_status", normalized)

    def test_complete_and_cancelled_version_two_round_trip_independently(self):
        for report in (self.complete, self.partial):
            with self.subTest(status=report["scan_status"]):
                original = deepcopy(report)
                normalized = load_report(json.dumps(report).encode())
                self.assertEqual(normalized, report)
                normalized["requested_ports"].append(80)
                details = scan_details(report)
                details["requested_ports"].clear()
                self.assertEqual(report, original)

    def test_cancelled_can_have_zero_or_all_requested_probes_completed(self):
        zero = deepcopy(self.partial)
        zero.update(results=[], open_ports=[], summary={"total": 0, "open": 0, "closed": 0, "timeout": 0, "error": 0})
        self.assertEqual(validate_report(zero)["summary"]["total"], 0)
        all_done = {**self.complete, "scan_status": "cancelled"}
        self.assertEqual(validate_report(all_done)["scan_status"], "cancelled")
        for status in ("completed", "cancelled"):
            empty = {**zero, "scan_status": status, "requested_ports": []}
            self.assertEqual(validate_report(empty)["requested_ports"], [])

    def test_completed_requires_exact_requested_coverage(self):
        for report in ({**self.partial, "scan_status": "completed"},
                       {**self.partial, "requested_ports": [9000]},
                       {**self.complete, "requested_ports": []}):
            with self.subTest(requested=report["requested_ports"]), self.assertRaises(ValueError):
                validate_report(report)

    def test_requested_ports_are_bounded_unique_integer_ports(self):
        for value in (None, {}, "8080", [True], [0], [65536], [8080.0], [8080, 8080], list(range(1, 1026))):
            with self.subTest(value=repr(value)[:60]), self.assertRaises(ValueError):
                validate_report({**self.partial, "requested_ports": value})

    def test_status_and_version_specific_fields_are_strict(self):
        for value in ("running", "failed", "partial", True, None, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_report({**self.partial, "scan_status": value})
        for field in ("scan_status", "requested_ports"):
            report = deepcopy(self.partial)
            del report[field]
            with self.assertRaises(ValueError):
                validate_report(report)
        for version in (1, None):
            report = {**self.partial, "schema_version": version}
            if version is None:
                del report["schema_version"]
            with self.assertRaises(ValueError):
                validate_report(report)

    def test_history_preserves_legacy_and_cancelled_payloads_without_database_migration(self):
        with TemporaryDirectory() as directory:
            db = Path(directory) / "history.db"
            legacy_id = save_report(self.legacy, db_path=db)
            partial_id = save_report(self.partial, db_path=db)
            with patch("socket.socket") as sockets:
                self.assertEqual(load_saved_report(legacy_id, db_path=db), self.legacy)
                self.assertEqual(load_saved_report(partial_id, db_path=db), self.partial)
                self.assertEqual(save_report(self.partial, db_path=db), partial_id)
                self.assertEqual(save_report(self.legacy, db_path=db), legacy_id)
            sockets.assert_not_called()
            self.assertEqual(len(list_reports(db_path=db)), 2)
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_comparison_includes_requested_ports_with_no_observations(self):
        partial = load_report((ROOT / "examples/localhost-stopped.json").read_bytes())
        partial.update(schema_version=2, scan_status="cancelled", requested_ports=[8080, 9000],
                       results=[], open_ports=[], summary={"total": 0, "open": 0, "closed": 0, "timeout": 0, "error": 0})
        comparison = compare_reports(self.legacy, partial)
        self.assertEqual(comparison["comparison_version"], 2)
        self.assertEqual(comparison["observation"]["scan_status"], "cancelled")
        self.assertEqual(comparison["baseline"]["scan_status"], "completed")
        self.assertEqual(comparison["coverage"]["unobserved"], [9000])
        self.assertEqual(comparison["summary"]["not_scanned"], 2)
        self.assertEqual(comparison["results"][0]["before_status"], "open")
        self.assertEqual(comparison["results"][0]["after_status"], "not scanned")
        self.assertEqual(comparison["results"][1]["before_status"], "not scanned")
        self.assertEqual(comparison["results"][1]["after_status"], "not scanned")
        self.assertTrue(any("Cancelled scan" in note for note in comparison["notes"]))


if __name__ == "__main__":
    unittest.main()
