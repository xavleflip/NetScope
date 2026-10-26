# Local scan history

NetScope can explicitly save validated reports in SQLite using Python's standard
library. No database server or extra package is required.

## Save, reopen, and export

1. Run a localhost scan, or import a valid NetScope JSON report.
2. Click **Save report** below that report. The success message shows its saved ID.
3. Under **Local history**, select that ID to review the report. The table lists
   scan time, target, result counts, duration, and when the report was saved.
4. Click **Download saved JSON report** to export the complete report, even when
   **Show only open ports** filters the displayed table.

Saved reports remain available after restarting NetScope. Scanning, importing,
filtering, listing, and reopening do not automatically save anything. Reopening
and downloading never start a new scan. There is no background collection,
automatic expiry, cloud sync, or history clearing.

Repeated saves of the same normalized report return the same ID without adding
another row. A new observation with different timestamps is a distinct report.
IDs remain stable while stored and are not reused after deletion.

Cancelled version-2 reports can be saved using **Save cancelled report**. Their
status and requested ports survive restart; reopened reports and downloads retain
the visible cancelled label. History table counts describe completed probes only;
select an entry to review its status and requested coverage. See
[progress and cancellation](progress-and-cancellation.md).

To inspect changes between two saved observations, use **Compare reports → Saved
history** and select the earlier baseline and later observation. See
[comparing reports](scan-comparison.md) for missing-coverage and uncertainty rules.

## Storage and validation

The database is `data/netscope.db`, relative to the folder containing `history.py`,
regardless of the current working directory. It is first created by an explicit
save. Viewing an empty history does not create the database or its directory.
The database and its SQLite journal/WAL sidecars are ignored by Git; reviewed
JSON examples under `examples/` remain eligible for version control.

History is **local and unencrypted**. It contains service labels, local ports,
connection outcomes, timestamps, and error details. Protect it with your normal
filesystem permissions and review exports before sharing them. Git ignores do
not prevent other local programs, users with access, or backup services from
reading the files.

`history.py` stores one validated, normalized JSON payload per report, plus
metadata for listing. It uses the same `reports.py` validation boundary as imports,
including the 1 MiB normalized payload limit and 1,024-result limit. Legacy reports
gain `schema_version: 1`; UTC timestamps are normalized. JSON formatting and key
order may change, while validated observations are preserved. Reopening validates
the stored payload again before displaying it.

A SHA-256 fingerprint supports duplicate detection and checks for accidental
payload changes. It is not a signature or proof that observations are authentic:
someone able to edit the database can also replace its fingerprint. See
[report validation](report-format.md) for the accepted data format.

## Delete a selected report

Select a report, click **Delete selected report**, then check the ID in the
warning. **Confirm delete report #ID** deletes only that entry; **Cancel deletion**
keeps it. Changing selection clears the pending confirmation. Export first if
you need a copy. Other saved reports and the live/imported report remain available.

Deletion cannot be undone through the app. It is not secure erasure: copies may
remain in backups, filesystem storage, or SQLite free pages. NetScope does not
silently delete history to make room for new reports.

## Backup and restore

For a portable copy of an individual report, use its JSON download. To recover it
later, import that file and click **Save report**. Importing alone does not add it
to history; an imported copy may receive a new ID.

To back up the complete history:

1. Stop all NetScope processes with **Ctrl+C**, and close other programs writing
   to this database.
2. Copy the entire `data` directory to a new private backup location. Keep any
   journal, `-wal`, or `-shm` files with it; do not copy just the database while a
   writer is active.
3. Keep the original and backup until you have verified that the copied history
   opens correctly. Do not commit the backup to Git.

For a backup while writers are active, use SQLite's backup API through an
appropriate SQLite tool rather than copying active database files.

To restore, stop all writers again. Move the current complete `data` directory
to a separate recovery location, then copy the complete known-good backup to
the project's `data` directory. Do not merge old and restored sidecar files.
Restart NetScope, select reports, and verify their contents. Keep the displaced
directory until recovery is confirmed. A restore replaces the active history
with that backup's contents; it does not merge later reports automatically.

## Storage failures and schema versions

Locked/busy, read-only, full, inaccessible, and corrupt storage produce visible
errors. Save failures leave the displayed report available for downloading.
Failed deletions preserve the pending confirmation so you can retry or cancel.
Transactions roll back failed writes; connections are short-lived and explicitly
closed. A competing writer can cause an error after a one-second lock wait.

Close competing database tools for lock errors, check directory permissions for
access errors, and free disk space for full storage. For corruption, preserve
the damaged directory before restoring a verified backup. The app never resets
or deletes a database to hide an error.

The database uses `PRAGMA user_version = 1`, independently of report JSON's schema
version. An empty database can be initialized on save. Unrecognized existing
schemas and unsupported versions fail without being reset. No data migration
is needed or implemented in this release. Any future migration that changes
stored data must begin with a verified backup and a recovery procedure.

Report versions 1 and 2 coexist in the same database schema. Adding cancellation
metadata required no database migration or rewrite of previously saved reports.

## Verification

Backend and dashboard history tests use isolated temporary databases and never
touch the project's real history. They cover save/reopen across connections and
a fresh Python process, a real local-listener scan followed by a fresh dashboard
session and JSON export, duplicate/concurrent saves, confirmed deletion, rollback,
invalid payloads, and storage failures. See [the test guide](../tests/README.md).
