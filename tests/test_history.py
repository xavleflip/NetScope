from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from history import HistoryError, delete_report, list_reports, load_saved_report, save_report
from reports import MAX_REPORT_BYTES, load_report


ROOT = Path(__file__).resolve().parents[1]


class HistoryTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "nested history" / "netscope.db"
        self.report = json.loads((ROOT / "examples/localhost-open.json").read_bytes())
        self.second = json.loads((ROOT / "examples/localhost-stopped.json").read_bytes())

    def test_reads_and_deletion_do_not_create_storage(self):
        self.assertEqual(list_reports(db_path=self.db), [])
        with self.assertRaises(HistoryError):
            load_saved_report(1, db_path=self.db)
        self.assertFalse(delete_report(1, db_path=self.db))
        self.assertFalse(self.db.parent.exists())

    def test_save_reopen_metadata_and_input_isolation(self):
        original = deepcopy(self.report)
        scan_id = save_report(self.report, db_path=self.db)
        self.assertEqual(self.report, original)
        self.assertEqual(load_saved_report(scan_id, db_path=self.db), {"schema_version": 1, **original})
        entry = list_reports(db_path=self.db)[0]
        self.assertEqual(entry["id"], scan_id)
        self.assertEqual(entry["target"], original["target"])
        self.assertEqual(entry["started_at"], original["started_at"])
        for status, count in original["summary"].items():
            self.assertEqual(entry[status], count)
        self.assertEqual(entry["duration_seconds"], original["duration_seconds"])
        self.assertTrue(entry["saved_at"].endswith("+00:00"))

    def test_repeated_normalized_saves_reuse_id(self):
        scan_id = save_report(self.report, db_path=self.db)
        reordered = dict(reversed(list(self.report.items())))
        self.assertEqual(save_report(reordered, db_path=self.db), scan_id)
        self.assertEqual(save_report({"schema_version": 1, **self.report}, db_path=self.db), scan_id)
        self.assertEqual(len(list_reports(db_path=self.db)), 1)

    def test_concurrent_duplicate_saves_have_one_row(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: save_report(self.report, db_path=self.db), range(4)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(list_reports(db_path=self.db)), 1)

    def test_selection_deletion_and_ids_never_reused(self):
        first_id = save_report(self.report, db_path=self.db)
        second_id = save_report(self.second, db_path=self.db)
        self.assertEqual([row["id"] for row in list_reports(db_path=self.db)], [second_id, first_id])
        self.assertTrue(delete_report(first_id, db_path=self.db))
        replacement_id = save_report(self.report, db_path=self.db)
        self.assertGreater(replacement_id, second_id)
        self.assertFalse(delete_report(first_id, db_path=self.db))
        self.assertEqual(len(list_reports(db_path=self.db)), 2)
        self.assertEqual(load_saved_report(second_id, db_path=self.db)["results"][0]["status"], "timeout")

    def test_persistence_in_a_fresh_python_process_without_scanning(self):
        scan_id = save_report(self.report, db_path=self.db)
        script = (
            "import json,sys; from unittest.mock import patch; from history import load_saved_report; "
            "guard=patch('socket.socket'); factory=guard.start(); "
            "print(json.dumps(load_saved_report(int(sys.argv[2]),db_path=sys.argv[1]))); "
            "factory.assert_not_called(); guard.stop()"
        )
        result = subprocess.run([sys.executable, "-c", script, str(self.db), str(scan_id)],
                                cwd=ROOT, capture_output=True, text=True, check=True, timeout=15)
        self.assertEqual(json.loads(result.stdout), {"schema_version": 1, **self.report})

    def test_invalid_and_oversized_reports_do_not_create_storage(self):
        with self.assertRaises(ValueError):
            save_report({}, db_path=self.db)
        huge = deepcopy(self.report)
        huge["results"][0]["service"] = "x" * MAX_REPORT_BYTES
        huge["open_ports"][0]["service"] = huge["results"][0]["service"]
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            save_report(huge, db_path=self.db)
        self.assertFalse(self.db.parent.exists())

    def test_invalid_ids_do_not_open_database(self):
        with patch("history.sqlite3.connect") as connect:
            for scan_id in (0, -1, True, "1 OR 1=1", 1.0, None):
                for operation in (load_saved_report, delete_report):
                    with self.subTest(scan_id=scan_id, operation=operation.__name__), self.assertRaises(ValueError):
                        operation(scan_id, db_path=self.db)
            connect.assert_not_called()

    def test_unreadable_path_is_an_error_instead_of_empty_history(self):
        with patch("history.Path.stat", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(HistoryError, "cannot be accessed"):
                list_reports(db_path=self.db)
            with self.assertRaisesRegex(HistoryError, "cannot be accessed"):
                delete_report(1, db_path=self.db)

    def test_bad_payload_is_not_repaired_or_deleted(self):
        scan_id = save_report(self.report, db_path=self.db)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE scans SET report_json = ? WHERE id = ?", ("{}", scan_id))
        with self.assertRaisesRegex(HistoryError, "validation"):
            load_saved_report(scan_id, db_path=self.db)
        with self.assertRaisesRegex(HistoryError, "identity"):
            save_report(self.report, db_path=self.db)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            self.assertEqual(connection.execute("SELECT report_json FROM scans").fetchone()[0], "{}")
        self.assertEqual(len(list_reports(db_path=self.db)), 1)

    def test_valid_but_modified_payload_fails_fingerprint_check(self):
        scan_id = save_report(self.report, db_path=self.db)
        changed = {"schema_version": 1, **self.report, "duration_seconds": 1.5}
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE scans SET report_json = ? WHERE id = ?", (json.dumps(changed), scan_id))
        with self.assertRaisesRegex(HistoryError, "integrity"):
            load_saved_report(scan_id, db_path=self.db)

    def test_failed_insert_and_delete_roll_back_without_data_loss(self):
        scan_id = save_report(self.report, db_path=self.db)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON scans BEGIN SELECT RAISE(ABORT,'test'); END")
            connection.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON scans BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(HistoryError):
            save_report(self.second, db_path=self.db)
        with self.assertRaises(HistoryError):
            delete_report(scan_id, db_path=self.db)
        self.assertEqual(len(list_reports(db_path=self.db)), 1)
        self.assertEqual(load_saved_report(scan_id, db_path=self.db), {"schema_version": 1, **self.report})

    def test_locked_storage_has_clear_error_and_preserves_report(self):
        scan_id = save_report(self.report, db_path=self.db)
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("BEGIN EXCLUSIVE")
            with self.assertRaisesRegex(HistoryError, "locked"):
                save_report(self.second, db_path=self.db)
        finally:
            connection.rollback()
            connection.close()
        self.assertEqual(load_saved_report(scan_id, db_path=self.db)["target"], "127.0.0.1")

    def test_read_only_storage_preserves_existing_data(self):
        scan_id = save_report(self.report, db_path=self.db)
        real_connect = sqlite3.connect
        def read_only(*args, **kwargs):
            return real_connect(self.db.resolve().as_uri() + "?mode=ro", uri=True)
        with patch("history.sqlite3.connect", side_effect=read_only):
            with self.assertRaisesRegex(HistoryError, "read-only"):
                save_report(self.second, db_path=self.db)
        self.assertEqual(load_saved_report(scan_id, db_path=self.db)["target"], "127.0.0.1")

    def test_full_storage_rolls_back_without_filling_disk(self):
        scan_id = save_report(self.report, db_path=self.db)
        real_connect = sqlite3.connect
        def capacity_limited(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            pages = connection.execute("PRAGMA page_count").fetchone()[0]
            connection.execute(f"PRAGMA max_page_count = {pages}")
            return connection
        larger = deepcopy(self.second)
        larger["results"][0]["service"] = "x" * 50000
        with patch("history.sqlite3.connect", side_effect=capacity_limited):
            with self.assertRaisesRegex(HistoryError, "full"):
                save_report(larger, db_path=self.db)
        self.assertEqual(load_saved_report(scan_id, db_path=self.db), {"schema_version": 1, **self.report})
        self.assertEqual(len(list_reports(db_path=self.db)), 1)

    def test_corrupt_database_is_not_reset(self):
        self.db.parent.mkdir(parents=True)
        original = b"This is not a SQLite database"
        self.db.write_bytes(original)
        for operation in (lambda: list_reports(db_path=self.db), lambda: save_report(self.report, db_path=self.db)):
            with self.assertRaisesRegex(HistoryError, "corrupt"):
                operation()
            self.assertEqual(self.db.read_bytes(), original)

    def test_future_schema_fails_without_modification(self):
        scan_id = save_report(self.report, db_path=self.db)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("PRAGMA user_version = 99")
        original = self.db.read_bytes()
        for operation in (lambda: list_reports(db_path=self.db), lambda: load_saved_report(scan_id, db_path=self.db),
                          lambda: save_report(self.second, db_path=self.db), lambda: delete_report(scan_id, db_path=self.db)):
            with self.assertRaisesRegex(HistoryError, "Unsupported"):
                operation()
            self.assertEqual(self.db.read_bytes(), original)

    def test_unknown_existing_schema_is_not_initialized(self):
        self.db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("CREATE TABLE other_data (value TEXT)")
            connection.execute("INSERT INTO other_data VALUES ('keep')")
        original = self.db.read_bytes()
        with self.assertRaisesRegex(HistoryError, "Unrecognized"):
            save_report(self.report, db_path=self.db)
        self.assertEqual(self.db.read_bytes(), original)

    def test_connections_are_closed_after_operations(self):
        real_connect = sqlite3.connect
        opened = []
        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            opened.append(connection)
            return connection
        with patch("history.sqlite3.connect", side_effect=connect):
            scan_id = save_report(self.report, db_path=self.db)
            list_reports(db_path=self.db)
            load_saved_report(scan_id, db_path=self.db)
            delete_report(scan_id, db_path=self.db)
        for connection in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
