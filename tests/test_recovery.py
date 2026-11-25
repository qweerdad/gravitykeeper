from contextlib import closing
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from gravitykeeper.capture import digest
from gravitykeeper.catalog import catalog, search, transcript
from gravitykeeper.demo import CONVERSATIONS, field, fixture, varint
from gravitykeeper.detection import probe
from gravitykeeper.errors import StorageError
from gravitykeeper.service import capture, export, full_backup
from gravitykeeper.storage import package_snapshot, verify_snapshot, verify_zip


FIRST = CONVERSATIONS[0][0]
LAST = CONVERSATIONS[-1][0]


def log_paths(source, uid):
    return source / "brain" / uid / ".system_generated" / "logs"


def bytes_in(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in root.rglob("*") if p.is_file()}


class Recovery(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix=".gk-test-", dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "源 profile"
        self.output = self.root / "归档 archive 🎈"

    def make(self, rows=0):
        return fixture(self.source, rows)

    def test_unicode_long_conversations_source_unchanged_and_export_roundtrip(self):
        self.make(6500)
        (self.source / "Cookies").write_bytes(b"fictional excluded marker")
        (log_paths(self.source, FIRST) / "credentials.txt").write_bytes(b"fictional excluded marker")
        before = bytes_in(self.source)
        events = []
        report = full_backup(self.output, self.source, lambda *event: events.append(event))
        self.assertEqual(report["raw"], "COMPLETE")
        self.assertEqual(report["export"], "COMPLETE")
        self.assertEqual(before, bytes_in(self.source))
        self.assertNotIn("Cookies", "\n".join(bytes_in(self.output)))
        self.assertNotIn("credentials.txt", "\n".join(bytes_in(self.output)))
        self.assertEqual({event[0] for event in events}, {"discover", "capture", "hash", "verify", "artifacts", "export"})
        projects = catalog(self.output)
        self.assertEqual(len(projects["projects"]), 2)
        rows = next(p["sessions"] for p in projects["projects"] if p["project_id"] == "transit studio")
        self.assertEqual(next(row["parent"] for row in rows if row["parent"]), FIRST)
        item = next(item for item in rows if item["uuid"] == FIRST)
        data = transcript(self.output, item)
        raw = [json.loads(line) for line in (log_paths(self.source, FIRST) / "transcript_full.jsonl").read_bytes().splitlines()]
        self.assertEqual(data["steps"], raw)
        markdown = (self.output / item["markdown"]).read_text(encoding="utf-8")
        for index in (0, 3250, 6499):
            self.assertIn(f'<a id="step-{index}"></a>', markdown)
            self.assertIn(raw[index]["content"], markdown)
        self.assertEqual(len(search(self.output, "城市博物馆")), 1)
        self.assertEqual(len(search(self.output, "rIVerSIDe")), 1)
        self.assertEqual(len(search(self.output, "Museum Workshop")), 2)
        self.assertTrue(list((self.output / "04_Brain_Artifacts").rglob("walkthrough.md")))
        self.assertTrue(list((self.output / "04_Brain_Artifacts").rglob("implementation_plan.md")))
        self.assertTrue(list((self.output / "04_Brain_Artifacts").rglob("001.log")))
        self.assertTrue(list((self.output / "04_Brain_Artifacts").rglob("synthetic-marker.png")))
        self.assertEqual(len(data["media_by_step"]["1"]), 1)

    def test_active_wal_contains_committed_steps_and_source_stays_unchanged(self):
        self.make()
        path = self.source / "conversations" / (FIRST + ".db")
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
            database.execute("PRAGMA wal_autocheckpoint=0")
            database.execute("INSERT INTO steps VALUES (9,132,?)", (b"test-committed-wal",))
            database.commit()
            self.assertGreater(Path(str(path) + "-wal").stat().st_size, 0)
            before = bytes_in(self.source)
            report = full_backup(self.output, self.source)
            self.assertEqual(before, bytes_in(self.source))
            self.assertEqual(report["raw"], "COMPLETE")
            self.assertEqual(report["export"], "PARTIAL")
            self.assertTrue(list((self.output / "01_Raw_Backup").rglob("*.db-wal")))
            materialized = next((self.output / "01_Raw_Backup" / "SQLite_Standalone").rglob(FIRST + ".db"))
            with closing(sqlite3.connect(materialized)) as staged:
                self.assertEqual(staged.execute("SELECT step_payload FROM steps WHERE idx=9").fetchone(), (b"test-committed-wal",))
            record = next(p for group in catalog(self.output)["projects"] for p in group["sessions"] if p["uuid"] == FIRST)
            self.assertEqual(transcript(self.output, record)["verification"]["missing_step_indices"], [9])

    def test_corrupt_database_retained_missing_transcript_reported(self):
        self.make()
        db = self.source / "conversations" / (LAST + ".db")
        db.write_bytes(db.read_bytes()[:128])
        log = log_paths(self.source, FIRST)
        for name in ("transcript.jsonl", "transcript_full.jsonl"):
            (log / name).unlink()
        for chunk in (log / "chunks" / "transcript_full").glob("*.jsonl"):
            chunk.unlink()
        summary = full_backup(self.output, self.source)
        self.assertEqual(summary["raw"], "COMPLETE")
        self.assertEqual(summary["export"], "PARTIAL")
        self.assertEqual(summary["sessions"], {"COMPLETE": 2, "PARTIAL": 1, "FAILED": 1})
        self.assertEqual(summary["database_warnings"][0]["code"], "database_corrupt")
        quarantined = self.output / summary["database_warnings"][0]["relative_path"]
        self.assertEqual(quarantined.read_bytes(), db.read_bytes())
        verify_snapshot(self.output)

    def test_chunks_salvage_a_missing_full_log(self):
        self.make()
        log = log_paths(self.source, FIRST)
        (log / "transcript_full.jsonl").unlink()
        (log / "transcript.jsonl").unlink()
        report = full_backup(self.output, self.source)
        self.assertEqual(report["sessions"], {"PARTIAL": 1, "COMPLETE": 3})
        row = next(p for group in catalog(self.output)["projects"] for p in group["sessions"] if p["uuid"] == FIRST)
        self.assertEqual(transcript(self.output, row)["verification"]["supplemental_chunk_steps"], [0, 1])

    def test_same_uuid_in_independent_profiles_uses_two_output_names(self):
        self.make()
        second = fixture(self.root / "Second profile")
        with patch("gravitykeeper.capture.sources", return_value=[("ProfileA", self.source), ("ProfileB", second)]):
            report = full_backup(self.output)
        self.assertEqual(report["sessions"], {"COMPLETE": 8})
        rows = [row for project in catalog(self.output)["projects"] for row in project["sessions"] if row["uuid"] == FIRST]
        self.assertEqual(len({row["json"] for row in rows}), 2)
        self.assertTrue(all((self.output / row["markdown"]).is_file() for row in rows))

    def test_hash_tampering_duplicate_destination_and_zip_extraction(self):
        self.make()
        self.assertEqual(capture(self.output, self.source)["export"], "NOT_RUN")
        self.assertEqual(export(self.output)["export"], "COMPLETE")
        with self.assertRaisesRegex(StorageError, "already has"):
            export(self.output)
        with self.assertRaises(StorageError) as error:
            capture(self.output, self.source)
        self.assertEqual(error.exception.code, "destination_exists")
        zip_path = self.root / "备份 archive.zip"
        result = package_snapshot(self.output, zip_path)
        self.assertEqual(verify_zip(zip_path)["sha256"], result["sha256"])
        unpacked = self.root / "Extracted"
        with ZipFile(zip_path) as archive:
            archive.extractall(unpacked)
        self.assertEqual(bytes_in(unpacked), bytes_in(self.output))
        verify_snapshot(unpacked)
        with self.assertRaises(StorageError):
            package_snapshot(self.output, zip_path)
        next(unpacked.rglob("transcript_full.jsonl")).write_bytes(b"changed")
        with self.assertRaises(StorageError) as caught:
            verify_snapshot(unpacked)
        self.assertEqual(caught.exception.code, "checksum_mismatch")

    def test_reject_unsafe_source_destination_and_simulated_low_disk(self):
        self.make()
        with self.assertRaises(StorageError) as caught:
            capture(self.source / "nested", self.source)
        self.assertEqual(caught.exception.code, "unsafe_destination")
        with patch("gravitykeeper.errors.shutil.disk_usage", return_value=type("DU", (), {"free": 1})()):
            with self.assertRaises(StorageError) as error:
                capture(self.output, self.source)
        self.assertEqual(error.exception.code, "disk_full")
        self.assertFalse(self.output.exists())

    def test_discovery_uses_read_only_catalogue_copy(self):
        self.make()
        before = bytes_in(self.source)
        with patch("tempfile.tempdir", str(self.root)):
            result = probe(self.source, include_workspaces=True, include_installations=False)
        self.assertEqual((result["conversations"], result["workspaces"]), (4, 2))
        self.assertEqual(result["installations"], [])
        self.assertEqual(before, bytes_in(self.source))

    def test_unsupported_binary_session_is_failed(self):
        self.source.mkdir()
        (self.source / "conversations").mkdir()
        (self.source / "conversations" / (FIRST + ".pb")).write_bytes(b"fictional opaque protobuf")
        report = full_backup(self.output, self.source)
        self.assertEqual((report["raw"], report["export"], report["sessions"]), ("COMPLETE", "FAILED", {"FAILED": 1}))

    def test_reject_zip_parent_traversal(self):
        path = self.root / "untrusted.zip"
        with ZipFile(path, "w") as archive:
            archive.writestr("../unexpected", "synthetic example")
        with self.assertRaises(StorageError) as caught:
            verify_zip(path)
        self.assertEqual(caught.exception.code, "unsafe_archive_entry")

    @unittest.skipUnless(os.name == "nt", "Requires Windows file sharing semantics")
    def test_windows_exclusive_handle_is_reported_and_only_other_data_copied(self):
        self.make()
        client = ctypes.WinDLL("kernel32", use_last_error=True)
        client.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        client.CreateFileW.restype = wintypes.HANDLE
        client.CloseHandle.argtypes = [wintypes.HANDLE]
        target = self.source / "conversations" / (FIRST + ".db")
        original = digest(target)
        handle = client.CreateFileW(str(target), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            summary = capture(self.output, self.source)
            self.assertEqual(summary["raw"], "PARTIAL")
            self.assertEqual(summary["capture_errors"][0]["code"], "file_locked")
        finally:
            client.CloseHandle(handle)
        self.assertEqual(digest(target), original)
        self.assertEqual(export(self.output)["sessions"], {"COMPLETE": 3, "PARTIAL": 1})

    def test_verified_wire_error_supplements_missing_tail(self):
        self.make()
        epoch = 1768471200  # 2026-01-15T10:00:00Z
        issue = "Fictional local error"
        metadata = field(1, varint(8) + varint(epoch))
        payload = field(24, field(3, field(2, issue.encode())))
        for uid in (FIRST, LAST):
            db = self.source / "conversations" / (uid + ".db")
            with closing(sqlite3.connect(db)) as conn:
                conn.executescript("ALTER TABLE steps ADD COLUMN metadata BLOB; ALTER TABLE steps ADD COLUMN status INT; ALTER TABLE steps ADD COLUMN step_format INT;")
                conn.execute("INSERT INTO steps VALUES (2,17,?,?,3,0)", (payload, metadata))
                conn.commit()
            with closing(sqlite3.connect(self.source / "conversation_summaries.db")) as index:
                index.execute("UPDATE conversation_summaries SET step_count=3 WHERE conversation_id=?", (uid,))
                index.commit()
        log = log_paths(self.source, FIRST)
        row = {"step_index": 2, "type": "ERROR_MESSAGE", "source": "SYSTEM", "status": "DONE",
               "created_at": "2026-01-15T10:00:00Z", "error": issue}
        added = (json.dumps(row) + "\n").encode()
        for name in ("transcript_full.jsonl", "chunks/transcript_full/00000001.jsonl"):
            with (log / name).open("ab") as stream:
                stream.write(added)
        result = full_backup(self.output, self.source)
        self.assertEqual(result["export"], "COMPLETE")
        target = next(item for group in catalog(self.output)["projects"] for item in group["sessions"] if item["uuid"] == LAST)
        rows = transcript(self.output, target)["steps"]
        self.assertEqual(rows[-1]["error"], issue)
        self.assertIn("recovered_from", rows[-1])


if __name__ == "__main__":
    unittest.main()
