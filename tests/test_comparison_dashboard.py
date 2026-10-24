import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from comparison import compare_reports
from history import HistoryError, delete_report, list_reports, save_report
from reports import MAX_REPORT_BYTES, load_report


ROOT = Path(__file__).resolve().parents[1]


class ComparisonDashboardTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "data" / "netscope.db"
        for name, kwargs in (
            ("history.DEFAULT_DB_PATH", {"new": self.db}),
            ("scanner.scan_target", {"side_effect": AssertionError("Comparison must not scan")}),
            ("scanner._scan_port_result", {"side_effect": AssertionError("Comparison must not probe")}),
            ("history.save_report", {"side_effect": AssertionError("Comparison must not save")}),
        ):
            patcher = patch(name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.before = (ROOT / "examples/localhost-open.json").read_bytes()
        self.after = (ROOT / "examples/localhost-stopped.json").read_bytes()

    def app(self, *, uploads=False):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        if uploads:
            app.radio(key="comparison_source").set_value("JSON files").run()
        return app

    def upload_pair(self, app, before=None, after=None):
        app.file_uploader(key="comparison_baseline_upload").set_value(
            ("before.json", self.before if before is None else before, "application/json"))
        app.file_uploader(key="comparison_observation_upload").set_value(
            ("after.json", self.after if after is None else after, "application/json")).run()
        self.assertFalse(app.exception)

    def comparison_downloads(self, download):
        return [call.kwargs for call in download.call_args_list
                if call.kwargs.get("key") == "comparison_download"]

    def test_two_uploads_show_uncertainty_and_export_the_visible_evidence(self):
        app = self.app(uploads=True)
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            self.upload_pair(app)
        exported = self.comparison_downloads(download)[-1]
        self.assertEqual(exported["file_name"], "comparison.json")
        self.assertEqual(exported["mime"], "application/json")
        comparison = json.loads(exported["data"])
        self.assertEqual(comparison, compare_reports(load_report(self.before), load_report(self.after)))
        table = app.dataframe[-1].value
        self.assertEqual(table["before_status"].tolist(), ["open"])
        self.assertEqual(table["after_status"].tolist(), ["timeout"])
        self.assertEqual(table["uncertain"].tolist(), [True])
        self.assertIn("not proof", table["interpretation"][0])
        self.assertEqual(app.dataframe[-2].value["role"].tolist(), ["Earlier baseline", "Later observation"])
        self.assertEqual([metric.value for metric in app.metric], ["1", "0", "0", "1"])
        self.assertFalse(self.db.exists())

    def test_saved_history_selection_is_explicit_and_comparison_does_not_write(self):
        first = save_report(load_report(self.before))
        second = save_report(load_report(self.after))
        original = self.db.read_bytes()
        app = self.app()
        self.assertIsNone(app.selectbox(key="comparison_baseline_id").value)
        self.assertIsNone(app.selectbox(key="comparison_observation_id").value)
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            app.selectbox(key="comparison_baseline_id").set_value(first).run()
            self.assertFalse(self.comparison_downloads(download))
            app.selectbox(key="comparison_observation_id").set_value(second).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[-1].value["after_status"].tolist(), ["timeout"])
        self.assertEqual(len(self.comparison_downloads(download)), 1)
        self.assertTrue(any(f"baseline: saved report #{first}" in caption.value for caption in app.caption))
        self.assertEqual(self.db.read_bytes(), original)
        self.assertEqual(len(list_reports()), 2)

    def test_reversed_reports_show_error_and_no_comparison_download(self):
        app = self.app(uploads=True)
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            self.upload_pair(app, before=self.after, after=self.before)
        self.assertTrue(any("Swap" in error.value for error in app.error))
        self.assertFalse(self.comparison_downloads(download))
        self.assertFalse(self.db.exists())

    def test_replaced_or_removed_upload_clears_comparison_and_preserves_live_report(self):
        app = self.app(uploads=True)
        app.session_state["report"] = load_report(self.before)
        self.upload_pair(app)
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            app.file_uploader(key="comparison_baseline_upload").set_value(
                ("invalid.json", b"{}", "application/json")).run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Comparison failed" in error.value for error in app.error))
            self.assertFalse(self.comparison_downloads(download))
            self.assertEqual(len(app.dataframe), 1)
            self.assertEqual(app.dataframe[0].value["status"].tolist(), ["open"])
            app.file_uploader(key="comparison_baseline_upload").clear().run()
            self.assertFalse(app.exception)
            self.assertFalse(self.comparison_downloads(download))
            self.assertEqual(app.session_state["report"], load_report(self.before))
        self.assertFalse(self.db.exists())

    def test_both_upload_boundaries_reject_oversized_files_and_external_targets(self):
        invalid = json.loads(self.before)
        invalid["target"] = "example.com"
        for role in ("baseline", "observation"):
            for data in (b" " * (MAX_REPORT_BYTES + 1), json.dumps(invalid).encode()):
                with self.subTest(role=role, size=len(data)):
                    app = self.app(uploads=True)
                    with patch("streamlit.download_button", wraps=st.download_button) as download:
                        app.file_uploader(key=f"comparison_{role}_upload").set_value(
                            ("invalid.json", data, "application/json")).run()
                    self.assertFalse(app.exception)
                    self.assertTrue(any("Comparison failed" in error.value for error in app.error))
                    self.assertFalse(self.comparison_downloads(download))
                    self.assertFalse(self.db.exists())

    def test_different_coverage_and_timeouts_are_visible(self):
        after = json.loads(self.after)
        after["results"][0]["port"] = 9999
        after["timeout_seconds"] = 0.05
        app = self.app(uploads=True)
        self.upload_pair(app, after=json.dumps(after).encode())
        self.assertTrue(any("coverage differs" in warning.value for warning in app.warning))
        self.assertTrue(any("timeout settings differ" in warning.value for warning in app.warning))
        self.assertEqual(app.dataframe[-2].value["timeout_seconds"].tolist(), [2.0, 0.05])
        table = app.dataframe[-1].value
        self.assertEqual(table["before_status"].tolist(), ["open", "not scanned"])
        self.assertEqual(table["after_status"].tolist(), ["not scanned", "timeout"])
        self.assertFalse(self.db.exists())

    def test_identical_saved_selection_and_deleted_selection(self):
        first = save_report(load_report(self.before))
        app = self.app()
        app.selectbox(key="comparison_baseline_id").set_value(first)
        app.selectbox(key="comparison_observation_id").set_value(first).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[-1].value["change"].tolist(), ["unchanged"])
        self.assertTrue(any("start times are equal" in warning.value for warning in app.warning))
        save_report(load_report(self.after))
        delete_report(first)
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            app.run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.selectbox(key="comparison_baseline_id").value)
        self.assertIsNone(app.selectbox(key="comparison_observation_id").value)
        self.assertFalse(self.comparison_downloads(download))

    def test_storage_failure_hides_comparison_without_destroying_history(self):
        first = save_report(load_report(self.before))
        second = save_report(load_report(self.after))
        app = self.app()
        app.selectbox(key="comparison_baseline_id").set_value(first)
        app.selectbox(key="comparison_observation_id").set_value(second).run()
        with patch("history.load_saved_report", side_effect=HistoryError("History database is locked.")), patch(
            "streamlit.download_button", wraps=st.download_button
        ) as download:
            app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Comparison failed" in error.value for error in app.error))
        self.assertFalse(self.comparison_downloads(download))
        self.assertEqual(len(list_reports()), 2)

    def test_empty_reports_and_source_changes_do_not_leave_old_comparisons(self):
        before = json.loads(self.before)
        after = json.loads(self.after)
        for report in (before, after):
            report.update(results=[], open_ports=[],
                          summary={"total": 0, "open": 0, "closed": 0, "timeout": 0, "error": 0})
        app = self.app(uploads=True)
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            self.upload_pair(app, before=json.dumps(before).encode(), after=json.dumps(after).encode())
        self.assertTrue(any("Neither report" in info.value for info in app.info))
        self.assertEqual(json.loads(self.comparison_downloads(download)[-1]["data"])["results"], [])
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            app.radio(key="comparison_source").set_value("Saved history").run()
        self.assertFalse(app.exception)
        self.assertFalse(self.comparison_downloads(download))
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
