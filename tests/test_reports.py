from copy import deepcopy
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from reports import MAX_REPORT_BYTES, load_report, validate_report
from scanner import scan_target


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.data = (EXAMPLES / "localhost-open.json").read_bytes()
        self.report = json.loads(self.data)

    def reject(self, report):
        with self.assertRaises(ValueError):
            validate_report(report)
        with self.assertRaises(ValueError):
            load_report(json.dumps(report).encode("utf-8"))

    def test_current_examples_load_without_io_or_socket_creation(self):
        for name in ("localhost-open.json", "localhost-stopped.json"):
            path = EXAMPLES / name
            data = path.read_bytes()
            original = json.loads(data)
            with patch("socket.socket") as factory, patch("builtins.open") as opened:
                normalized = load_report(data)
                factory.assert_not_called()
                opened.assert_not_called()
            self.assertEqual(normalized, {"schema_version": 1, **original})
            self.assertEqual(path.read_bytes(), data)

    def test_normalization_does_not_mutate_or_share_nested_input(self):
        original = deepcopy(self.report)
        normalized = validate_report(self.report)
        self.assertEqual(self.report, original)
        normalized["results"][0]["service"] = "changed"
        normalized["open_ports"][0]["service"] = "changed"
        normalized["summary"]["open"] = 999
        self.assertEqual(self.report, original)

    def test_new_real_scan_is_versioned_and_round_trips(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            report = scan_target("localhost", start_port=port, end_port=port, timeout=0.1)
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(load_report(json.dumps(report).encode("utf-8")), report)

    def test_version_types_and_unsupported_versions_are_rejected(self):
        for version in (0, 3, -1, True, 1.0, "1", None, []):
            with self.subTest(version=version):
                self.reject({**self.report, "schema_version": version})

    def test_missing_and_unsupported_fields_are_rejected(self):
        for field in self.report:
            with self.subTest(missing=field):
                report = deepcopy(self.report)
                del report[field]
                self.reject(report)
        self.reject({**self.report, "output_path": "untrusted-path.json"})

    def test_non_object_roots_and_malformed_json_are_rejected(self):
        for data in (b"", b"{", b"[]", b"true", b"null", b"123", b'"text"', b"\xff"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_report(data)
        with self.assertRaises(ValueError):
            load_report(b"[" * 1500 + b"]" * 1500)
        with self.assertRaises(ValueError):
            load_report("not bytes")

    def test_duplicate_json_keys_are_rejected_even_if_last_value_would_be_valid(self):
        text = self.data.decode("utf-8")
        duplicates = (
            '{"target": "localhost",' + text[1:],
            text.replace('"port": 8080', '"port": 80, "port": 8080', 1),
            text.replace('"total": 1', '"total": 0, "total": 1', 1),
        )
        for duplicate in duplicates:
            with self.subTest(text=duplicate), self.assertRaises(ValueError):
                load_report(duplicate.encode("utf-8"))

    def test_import_byte_limit_including_exact_boundary(self):
        padded = self.data + b" " * (MAX_REPORT_BYTES - len(self.data))
        self.assertEqual(load_report(padded), {"schema_version": 1, **self.report})
        with patch("reports.json.loads") as parse:
            with self.assertRaisesRegex(ValueError, "1 MiB"):
                load_report(padded + b" ")
            parse.assert_not_called()

    def test_port_limit_and_empty_reports(self):
        report = deepcopy(self.report)
        report["results"] = [{"port": port, "service": "unknown", "status": "closed"}
                             for port in range(1, 1025)]
        report["open_ports"] = []
        report["summary"] = {"total": 1024, "open": 0, "closed": 1024, "timeout": 0, "error": 0}
        self.assertEqual(len(validate_report(report)["results"]), 1024)
        report["results"].append({"port": 1025, "service": "unknown", "status": "closed"})
        self.reject(report)
        report["results"] = []
        report["summary"] = {"total": 0, "open": 0, "closed": 0, "timeout": 0, "error": 0}
        self.assertEqual(validate_report(report)["results"], [])

    def test_targets_follow_the_scanner_allowlist(self):
        for target in ("example.com", "192.0.2.1", "127.0.0.2", "::1", " localhost", None):
            with self.subTest(target=target):
                self.reject({**self.report, "target": target})
        self.assertEqual(validate_report({**self.report, "target": "localhost"})["target"], "localhost")

    def test_timestamps_are_required_valid_utc_and_consistent(self):
        invalid = (
            "2026-10-24T03:03:09", "2026-10-24T10:03:09+07:00", "2026-02-30T00:00:00Z",
            "2026-10-24 03:03:09+00:00", "2026-10-24T25:00:00Z", "", None, 123,
        )
        for field in ("timestamp", "started_at", "finished_at"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    self.reject({**self.report, field: value})
        self.reject({**self.report, "timestamp": "2026-10-24T00:00:00Z"})
        self.reject({**self.report, "finished_at": "2026-10-24T00:00:00Z"})

    def test_utc_z_and_utf8_bom_normalize_without_changing_meaning(self):
        report = deepcopy(self.report)
        for field in ("timestamp", "started_at", "finished_at"):
            report[field] = report[field].replace("+00:00", "Z")
        normalized = load_report(b"\xef\xbb\xbf" + json.dumps(report).encode("utf-8"))
        self.assertEqual(normalized, {"schema_version": 1, **self.report})

    def test_durations_and_timeouts_are_finite_and_in_range(self):
        for value in (-1, True, None, "1", float("nan"), float("inf"), 10 ** 400):
            with self.subTest(duration=value):
                self.reject({**self.report, "duration_seconds": value})
        for value in (0, 0.049, 2.001, True, None, "0.5", float("nan"), float("inf")):
            with self.subTest(timeout=value):
                self.reject({**self.report, "timeout_seconds": value})
        overflow = self.data.replace(b'"duration_seconds": 0.007542', b'"duration_seconds": 1e999')
        with self.assertRaises(ValueError):
            load_report(overflow)
        # Monotonic duration need not equal the difference between wall-clock times.
        self.assertEqual(validate_report({**self.report, "duration_seconds": 123})["duration_seconds"], 123)

    def test_result_types_ports_statuses_and_text(self):
        for key, value in (("port", 0), ("port", 65536), ("port", True), ("port", 8080.0),
                           ("service", None), ("service", ""), ("service", "\ud800"),
                           ("status", "filtered"), ("status", []), ("status", None)):
            with self.subTest(key=key, value=value):
                report = deepcopy(self.report)
                report["results"][0][key] = value
                self.reject(report)
        for value in (None, {}, [None], [{"port": 80}]):
            self.reject({**self.report, "results": value})
        self.reject({**self.report, "results": self.report["results"] * 2})

    def test_error_details_are_consistent_with_status(self):
        report = deepcopy(self.report)
        report["results"][0]["status"] = "error"
        report["open_ports"] = []
        report["summary"].update(open=0, error=1)
        self.reject(report)
        report["results"][0]["error"] = 123
        self.reject(report)
        report["results"][0]["error"] = "unavailable"
        self.assertEqual(validate_report(report)["results"][0]["error"], "unavailable")
        report = deepcopy(self.report)
        report["results"][0]["error"] = "unexpected"
        self.reject(report)

    def test_summary_types_fields_and_counts(self):
        for summary in ([], {}, {**self.report["summary"], "total": True},
                        {**self.report["summary"], "open": -1},
                        {**self.report["summary"], "total": 2},
                        {**self.report["summary"], "closed": 1},
                        {**self.report["summary"], "filtered": 0}):
            with self.subTest(summary=summary):
                self.reject({**self.report, "summary": summary})

    def test_open_ports_must_match_full_results(self):
        for rows in (None, [], self.report["open_ports"] * 2,
                     [{"port": 80, "service": "unknown"}],
                     [{"port": 8080, "service": "different"}],
                     [{"port": True, "service": "unknown"}],
                     [{"port": 8080, "service": "unknown", "status": "open"}]):
            with self.subTest(rows=rows):
                self.reject({**self.report, "open_ports": rows})


if __name__ == "__main__":
    unittest.main()
