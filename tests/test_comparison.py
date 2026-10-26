from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from comparison import compare_reports
from reports import load_report, validate_report


ROOT = Path(__file__).resolve().parents[1]


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.before = load_report((ROOT / "examples/localhost-open.json").read_bytes())
        self.after = load_report((ROOT / "examples/localhost-stopped.json").read_bytes())

    def report(self, rows, *, later=False):
        report = deepcopy(self.after if later else self.before)
        report["results"] = rows
        report["summary"] = {"total": len(rows), **{
            status: sum(row["status"] == status for row in rows)
            for status in ("open", "closed", "timeout", "error")
        }}
        report["open_ports"] = [{"port": row["port"], "service": row["service"]}
                                for row in rows if row["status"] == "open"]
        return validate_report(report)

    def test_recorded_examples_preserve_open_to_timeout_uncertainty(self):
        comparison = compare_reports(self.before, self.after)
        self.assertEqual(comparison["target"], "127.0.0.1")
        self.assertEqual(comparison["coverage"], {"shared": [8080], "baseline_only": [], "observation_only": [], "unobserved": []})
        self.assertEqual(comparison["summary"], {
            "total": 1, "status_changed": 1, "status_unchanged": 0,
            "not_scanned": 0, "uncertain": 1, "service_label_changed": 0,
        })
        row = comparison["results"][0]
        self.assertEqual((row["before_status"], row["after_status"]), ("open", "timeout"))
        self.assertIn("not proof", row["interpretation"])
        self.assertEqual(comparison["baseline"]["summary"]["open"], 1)
        self.assertEqual(comparison["observation"]["summary"]["timeout"], 1)

    def test_all_sixteen_status_transitions(self):
        statuses = ("open", "closed", "timeout", "error")
        for before in statuses:
            for after in statuses:
                with self.subTest(before=before, after=after):
                    rows = []
                    for status in (before, after):
                        row = {"port": 80, "service": "http", "status": status}
                        if status == "error":
                            row["error"] = "controlled failure"
                        rows.append(row)
                    comparison = compare_reports(self.report([rows[0]]), self.report([rows[1]], later=True))
                    result = comparison["results"][0]
                    uncertain = before in ("timeout", "error") or after in ("timeout", "error")
                    self.assertEqual((result["before_status"], result["after_status"]), (before, after))
                    self.assertEqual(result["change"], "unchanged" if before == after else "changed")
                    self.assertEqual(result["uncertain"], uncertain)
                    self.assertEqual(comparison["summary"]["uncertain"], int(uncertain))
                    self.assertEqual(comparison["summary"]["status_changed"], int(before != after))
                    self.assertEqual(comparison["summary"]["status_unchanged"], int(before == after))
                    if uncertain:
                        self.assertIn("Uncertain", result["interpretation"])
                    elif "closed" in (before, after):
                        self.assertIn("refused", result["interpretation"])

    def test_coverage_is_sorted_and_missing_is_distinct_from_closed(self):
        baseline = self.report([
            {"port": 80, "service": "http", "status": "open"},
            {"port": 1, "service": "unknown", "status": "closed"},
        ])
        observation = self.report([
            {"port": 65535, "service": "unknown", "status": "timeout"},
            {"port": 80, "service": "http", "status": "closed"},
        ], later=True)
        comparison = compare_reports(baseline, observation)
        self.assertEqual(comparison["coverage"], {"shared": [80], "baseline_only": [1], "observation_only": [65535], "unobserved": []})
        rows = comparison["results"]
        self.assertEqual([row["port"] for row in rows], [1, 80, 65535])
        self.assertEqual((rows[0]["before_status"], rows[0]["after_status"]), ("closed", "not scanned"))
        self.assertEqual((rows[2]["before_status"], rows[2]["after_status"]), ("not scanned", "timeout"))
        self.assertIsNone(rows[0]["after_service"])
        self.assertIsNone(rows[2]["before_error"])
        self.assertEqual(rows[2]["change"], "not scanned")
        self.assertTrue(rows[2]["uncertain"])
        self.assertEqual(comparison["summary"]["not_scanned"], 2)
        self.assertEqual(comparison["summary"]["status_changed"], 1)
        self.assertTrue(any("coverage differs" in note for note in comparison["notes"]))

    def test_identical_reports_include_unchanged_and_uncertain_observations(self):
        for report in (self.before, self.after):
            with self.subTest(status=report["results"][0]["status"]):
                comparison = compare_reports(report, report)
                self.assertEqual(comparison["summary"]["status_changed"], 0)
                self.assertEqual(comparison["summary"]["status_unchanged"], 1)
                self.assertEqual(comparison["results"][0]["uncertain"], report is self.after)
                self.assertTrue(any("start times are equal" in note for note in comparison["notes"]))

    def test_empty_reports_and_one_sided_coverage(self):
        empty = self.report([])
        comparison = compare_reports(empty, self.report([], later=True))
        self.assertEqual(comparison["results"], [])
        self.assertTrue(all(count == 0 for count in comparison["summary"].values()))
        comparison = compare_reports(empty, self.after)
        self.assertEqual(comparison["summary"]["not_scanned"], 1)
        self.assertEqual(comparison["results"][0]["before_status"], "not scanned")

    def test_loopback_aliases_match_without_dns(self):
        alias = deepcopy(self.after)
        alias["target"] = "localhost"
        with patch("socket.getaddrinfo") as dns, patch("socket.gethostbyname") as resolve:
            comparison = compare_reports(self.before, alias)
        dns.assert_not_called()
        resolve.assert_not_called()
        self.assertEqual(comparison["target"], "127.0.0.1")
        self.assertEqual(comparison["observation"]["target"], "localhost")
        self.assertEqual(comparison["coverage"]["shared"], [8080])

    def test_comparison_is_pure_deterministic_and_independent(self):
        originals = deepcopy((self.before, self.after))
        with patch("socket.socket") as socket, patch("socket.create_connection") as connect, patch(
            "builtins.open"
        ) as files, patch("pathlib.Path.open") as paths, patch("sqlite3.connect") as database:
            first = compare_reports(self.before, self.after)
            second = compare_reports(self.before, self.after)
        for boundary in (socket, connect, files, paths, database):
            boundary.assert_not_called()
        self.assertEqual(first, second)
        self.assertEqual(json.loads(json.dumps(first, allow_nan=False)), first)
        first["baseline"]["summary"]["open"] = 999
        first["results"][0]["before_service"] = "changed"
        first["coverage"]["shared"].clear()
        self.assertEqual((self.before, self.after), originals)
        self.assertEqual(second["baseline"]["summary"]["open"], 1)

    def test_reversed_chronology_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Swap"):
            compare_reports(self.after, self.before)

    def test_equal_instants_and_overlapping_scan_windows_are_explained(self):
        equal = deepcopy(self.before)
        equal["timestamp"] = equal["started_at"] = self.before["started_at"].replace("+00:00", "Z")
        self.assertTrue(any("start times are equal" in note
                            for note in compare_reports(self.before, equal)["notes"]))
        overlapping = deepcopy(self.before)
        overlapping["finished_at"] = self.after["finished_at"]
        self.assertTrue(any("windows overlap" in note
                            for note in compare_reports(overlapping, self.after)["notes"]))

    def test_timeout_settings_are_preserved_and_difference_is_explicit(self):
        after = deepcopy(self.after)
        after["timeout_seconds"] = 0.05
        comparison = compare_reports(self.before, after)
        self.assertTrue(comparison["timeouts_differ"])
        self.assertEqual(comparison["baseline"]["timeout_seconds"], 2.0)
        self.assertEqual(comparison["observation"]["timeout_seconds"], 0.05)
        self.assertTrue(any("timeout settings differ" in note for note in comparison["notes"]))

    def test_label_changes_and_error_details_are_separate_from_status_changes(self):
        baseline = self.report([{"port": 80, "service": "http", "status": "open"}])
        after = self.report([{"port": 80, "service": "other label", "status": "open"}], later=True)
        comparison = compare_reports(baseline, after)
        self.assertEqual(comparison["summary"]["status_unchanged"], 1)
        self.assertEqual(comparison["summary"]["service_label_changed"], 1)
        row = comparison["results"][0]
        self.assertEqual((row["before_service"], row["after_service"]), ("http", "other label"))
        self.assertTrue(row["service_label_changed"])
        baseline = self.report([{"port": 80, "service": "http", "status": "error", "error": "first failure"}])
        after = self.report([{"port": 80, "service": "http", "status": "error", "error": "second failure"}], later=True)
        row = compare_reports(baseline, after)["results"][0]
        self.assertEqual(row["change"], "unchanged")
        self.assertTrue(row["uncertain"])
        self.assertEqual((row["before_error"], row["after_error"]), ("first failure", "second failure"))

    def test_invalid_reports_are_rejected_by_shared_validation(self):
        invalid = deepcopy(self.after)
        invalid["target"] = "example.com"
        for before, after in (({}, self.after), (self.before, invalid)):
            with self.subTest(before=before.get("target")), self.assertRaises(ValueError):
                compare_reports(before, after)

    def test_disjoint_maximum_size_reports_keep_the_entire_union(self):
        before = self.report([{"port": port, "service": "unknown", "status": "closed"}
                              for port in range(1, 1025)])
        after = self.report([{"port": port, "service": "unknown", "status": "open"}
                             for port in range(1025, 2049)], later=True)
        comparison = compare_reports(before, after)
        self.assertEqual(comparison["summary"]["total"], 2048)
        self.assertEqual(comparison["summary"]["not_scanned"], 2048)
        self.assertEqual(comparison["summary"]["status_changed"], 0)
        self.assertEqual(len(comparison["results"]), 2048)


if __name__ == "__main__":
    unittest.main()
