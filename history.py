"""Explicit local report persistence with short-lived SQLite transactions."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from reports import MAX_REPORT_BYTES, load_report, validate_report


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "netscope.db"
DB_VERSION = 1


class HistoryError(RuntimeError):
    """A storage operation failed without resetting the history database."""


def _storage_message(exc):
    code = (getattr(exc, "sqlite_errorcode", 0) or 0) & 0xFF
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return "History database is busy or locked. Try again when the other operation finishes."
    if code == sqlite3.SQLITE_READONLY:
        return "History database is read-only. Check database and folder permissions."
    if code == sqlite3.SQLITE_FULL:
        return "History storage is full. Free disk space and try again."
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return "History database is corrupt or is not a SQLite database. Restore a verified backup."
    if code in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_PERM, sqlite3.SQLITE_AUTH):
        return "History storage cannot be opened. Check folder permissions and availability."
    return "History storage operation failed. The database has not been reset."


def _schema(connection, initialize):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == DB_VERSION:
        return True
    if version != 0:
        raise HistoryError("Unsupported history database version. The database was left unchanged.")
    existing = connection.execute(
        "SELECT name FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' LIMIT 1"
    ).fetchone()
    if existing:
        raise HistoryError("Unrecognized history database schema. The database was left unchanged.")
    if not initialize:
        return False
    connection.execute("""
        CREATE TABLE scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL UNIQUE,
            saved_at TEXT NOT NULL,
            started_at TEXT NOT NULL,
            target TEXT NOT NULL,
            total INTEGER NOT NULL,
            open_count INTEGER NOT NULL,
            closed_count INTEGER NOT NULL,
            timeout_count INTEGER NOT NULL,
            error_count INTEGER NOT NULL,
            duration_seconds REAL NOT NULL,
            report_json TEXT NOT NULL
        )
    """)
    connection.execute("PRAGMA user_version = 1")
    return True


@contextmanager
def _connection(db_path, *, write=False, create=False):
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    try:
        if not create:
            try:
                path.stat()
            except FileNotFoundError:
                yield None
                return
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        mode = "rwc" if create else ("rw" if write else "ro")
        uri = path.resolve().as_uri() + f"?mode={mode}"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.row_factory = sqlite3.Row
            # The connection context commits on success and rolls back on failure;
            # closing() also releases handles after failed commits and reads.
            with connection:
                if write:
                    connection.execute("BEGIN IMMEDIATE")
                ready = _schema(connection, initialize=create)
                yield connection if ready else None
    except sqlite3.Error as exc:
        raise HistoryError(_storage_message(exc)) from exc
    except OSError as exc:
        raise HistoryError("History folder cannot be accessed. Check disk space and folder permissions.") from exc


def _scan_id(scan_id):
    if type(scan_id) is not int or scan_id <= 0:
        raise ValueError("Saved report ID must be a positive integer.")


def save_report(report, *, db_path=None):
    """Save normalized evidence once; return its stable ID, including on retries."""
    normalized = validate_report(report)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("Normalized report exceeds the 1 MiB history limit.")
    fingerprint = hashlib.sha256(encoded).hexdigest()
    summary = normalized["summary"]
    with _connection(db_path, write=True, create=True) as connection:
        connection.execute("""
            INSERT INTO scans (
                fingerprint, saved_at, started_at, target, total, open_count,
                closed_count, timeout_count, error_count, duration_seconds, report_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO NOTHING
        """, (fingerprint, datetime.now(timezone.utc).isoformat(), normalized["started_at"],
              normalized["target"], summary["total"], summary["open"], summary["closed"],
              summary["timeout"], summary["error"], float(normalized["duration_seconds"]), payload))
        saved = connection.execute(
            "SELECT id, report_json FROM scans WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if saved["report_json"] != payload:
            raise HistoryError("Existing saved report failed its identity check. The database was left unchanged.")
        return saved["id"]


def list_reports(*, db_path=None):
    """List compact summaries, newest saves first. A missing database stays absent."""
    with _connection(db_path) as connection:
        if connection is None:
            return []
        rows = connection.execute("""
            SELECT id, saved_at, started_at, target, total, open_count AS open,
                   closed_count AS closed, timeout_count AS timeout, error_count AS error,
                   duration_seconds
            FROM scans ORDER BY id DESC
        """).fetchall()
        return [dict(row) for row in rows]


def load_saved_report(scan_id, *, db_path=None):
    """Revalidate stored evidence on every reopen; never repair or drop bad rows."""
    _scan_id(scan_id)
    with _connection(db_path) as connection:
        row = None if connection is None else connection.execute(
            "SELECT report_json, fingerprint FROM scans WHERE id = ?", (scan_id,)
        ).fetchone()
    if row is None:
        raise HistoryError("Saved report no longer exists. Refresh the history list.")
    try:
        payload = row["report_json"]
        if not isinstance(payload, str):
            raise ValueError("Invalid stored payload")
        encoded = payload.encode("utf-8")
        normalized = load_report(encoded)
        if hashlib.sha256(encoded).hexdigest() != row["fingerprint"]:
            raise ValueError("Stored payload fingerprint differs")
        return normalized
    except ValueError as exc:
        raise HistoryError("Saved report failed validation or its integrity check. It was not modified.") from exc


def delete_report(scan_id, *, db_path=None):
    """Delete only the given stable ID; return False if it was already removed."""
    _scan_id(scan_id)
    # Deleting from an absent database must not create one.
    with _connection(db_path, write=True) as connection:
        if connection is None:
            return False
        return connection.execute("DELETE FROM scans WHERE id = ?", (scan_id,)).rowcount == 1
