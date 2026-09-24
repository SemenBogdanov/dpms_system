from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import record_boot as recorder


NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)


def event(identity="a", age=0, recorded_at=NOW):
    return recorder.BootEvent(identity * 32, NOW - timedelta(days=age), recorded_at, 42.5)


class BootRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.events = self.root / "events"

    def tearDown(self):
        self.temp.cleanup()

    def test_text_roundtrip_and_permissions(self):
        expected = event()
        path, created = recorder.write_event(self.events, expected)
        self.assertTrue(created)
        self.assertEqual(recorder.decode_event(path), expected)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.events.stat().st_mode), 0o750)
        self.assertIn("DPMS", path.read_text())
        self.assertIn("reason = unknown", path.read_text())
        self.assertLess(path.stat().st_size, 2048)

    def test_repeat_preserves_first_record_even_after_clock_change(self):
        path, _ = recorder.write_event(self.events, event())
        before = path.read_bytes()
        later = recorder.BootEvent("a" * 32, NOW + timedelta(hours=2), NOW + timedelta(hours=3), 9999)
        _, created = recorder.write_event(self.events, later)
        self.assertFalse(created)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list(self.events.glob("boot-*.txt"))), 1)

    def test_new_boot_produces_second_event(self):
        recorder.write_event(self.events, event("a", 1))
        recorder.write_event(self.events, event("b", 0))
        self.assertEqual(len(list(self.events.glob("boot-*.txt"))), 2)

    def test_concurrent_writers_publish_only_one_complete_event(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: recorder.write_event(self.events, event()), range(16)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(recorder.decode_event(results[0][0]), event())
        self.assertFalse(list(self.events.glob(".boot-pending-*")))

    def test_publish_failure_does_not_leave_partial_event(self):
        with patch.object(recorder.os, "link", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                recorder.write_event(self.events, event())
        self.assertEqual(list(self.events.iterdir()), [])
        self.assertTrue(recorder.write_event(self.events, event())[1])

    def test_fsync_failure_does_not_publish(self):
        with patch.object(recorder.os, "fsync", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                recorder.write_event(self.events, event())
        self.assertEqual(list(self.events.iterdir()), [])

    def test_retry_repeats_directory_fsync_without_duplicating_published_event(self):
        real_sync = recorder.os.fsync
        calls = []

        def fail_directory_once(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError("simulated directory sync failure")
            real_sync(fd)

        with patch.object(recorder.os, "fsync", side_effect=fail_directory_once):
            with self.assertRaises(OSError):
                recorder.write_event(self.events, event())
        self.assertEqual(len(list(self.events.glob("boot-*.txt"))), 1)
        with patch.object(recorder.os, "fsync", wraps=real_sync) as sync:
            path, created = recorder.write_event(self.events, event())
            self.assertFalse(created)
            self.assertEqual(sync.call_count, 3)
            self.assertEqual(recorder.decode_event(path), event())

    def test_parent_directory_is_synced_on_first_run_and_retry(self):
        original_sync = recorder.os.fsync
        original_open = recorder.os.open
        directory_paths = []

        def observed_open(path, flags, *args, **kwargs):
            if flags & recorder.os.O_DIRECTORY:
                directory_paths.append(Path(path))
            return original_open(path, flags, *args, **kwargs)

        for _ in range(2):
            directory_paths.clear()
            with patch.object(recorder.os, "open", side_effect=observed_open), patch.object(recorder.os, "fsync", wraps=original_sync) as sync:
                recorder.write_event(self.events, event())
                self.assertEqual(directory_paths, [self.events, self.events.parent])
                self.assertEqual(sync.call_count, 3)

    def test_missing_parent_requires_explicit_setup_not_implicit_directory_tree(self):
        with self.assertRaises(FileNotFoundError):
            recorder.write_event(self.root / "missing" / "events", event())
        self.assertFalse((self.root / "missing").exists())

    def test_invalid_id_cannot_escape_directory(self):
        bad = recorder.BootEvent("../escape", NOW, NOW, 0)
        with self.assertRaises(ValueError):
            recorder.write_event(self.events, bad)
        self.assertFalse(self.events.exists())

    def test_symlink_directory_rejected(self):
        target = self.root / "target"
        target.mkdir()
        self.events.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            recorder.write_event(self.events, event())
        self.assertEqual(list(target.iterdir()), [])

    def test_existing_symlink_or_corrupt_event_is_not_overwritten(self):
        self.events.mkdir()
        path = self.events / f"boot-{'a' * 32}.txt"
        path.write_text("broken")
        with self.assertRaises(Exception):
            recorder.write_event(self.events, event())
        self.assertEqual(path.read_text(), "broken")
        path.unlink()
        target = self.root / "do-not-touch.txt"
        target.write_text("untouched")
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            recorder.write_event(self.events, event())
        self.assertEqual(target.read_text(), "untouched")

    def test_week_report_counts_boot_time_not_record_time_and_sorts(self):
        for item in [event("b", 0), event("c", 8), event("a", 2)]:
            recorder.write_event(self.events, item)
        output = recorder.report(self.events, now=NOW)
        self.assertIn("Обнаруженных загрузок за период: 2", output)
        self.assertIn("Всего сохранённых событий: 3", output)
        self.assertLess(output.index("a" * 32), output.index("b" * 32))
        self.assertNotIn("c" * 32, output)
        self.assertIn("не равен числу аварий", output)

    def test_no_history_never_claims_stability_or_creates_directory(self):
        output = recorder.report(self.events, now=NOW)
        self.assertIn("Нет записей", output)
        self.assertIn("не доказательство", output)
        self.assertFalse(self.events.exists())

    def test_future_clock_warning(self):
        recorder.write_event(self.events, event("a", -1))
        output = recorder.report(self.events, now=NOW)
        self.assertIn("загрузок за период: 0", output)
        self.assertIn("будущими датами: 1", output)

    def test_invalid_file_warns_without_echoing_its_content(self):
        self.events.mkdir()
        (self.events / f"boot-{'a' * 32}.txt").write_text("UNTRUSTED_TEXT")
        output = recorder.report(self.events, now=NOW)
        self.assertIn("файлов: 1", output)
        self.assertNotIn("UNTRUSTED_TEXT", output)

    def test_oversized_event_rejected(self):
        self.events.mkdir()
        path = self.events / f"boot-{'a' * 32}.txt"
        path.write_bytes(b"x" * (recorder.MAX_EVENT_BYTES + 1))
        with self.assertRaises(ValueError):
            recorder.decode_event(path)

    def test_report_range_validation(self):
        for days in [0, -1, 367]:
            with self.assertRaises(ValueError):
                recorder.report(self.events, days=days, now=NOW)

    def test_kernel_reader_uses_boot_id_and_btime(self):
        proc = self.root / "proc"
        location = proc / "sys/kernel/random"
        location.mkdir(parents=True)
        raw_id = "11111111-1111-4111-8111-111111111111"
        (location / "boot_id").write_text(raw_id)
        (proc / "uptime").write_text("42.5 123.0\n")
        (proc / "stat").write_text(f"cpu 0 0 0\nbtime {int(NOW.timestamp())}\nprocesses 10\n")
        result = recorder.read_boot(proc, now=NOW)
        self.assertEqual(result.booted_at, NOW)
        self.assertEqual(result.recorded_at, NOW)
        self.assertEqual(result.uptime_seconds, 42.5)
        self.assertNotIn(raw_id, recorder.encode_event(result))
        self.assertEqual(len(result.event_id), 32)
        (proc / "uptime").write_text("nan 0")
        with self.assertRaises(ValueError):
            recorder.read_boot(proc, now=NOW)

    def test_service_starts_on_host_boot_without_network_or_docker_dependency(self):
        unit = (Path(__file__).parent / "dpms-boot-record.service").read_text()
        self.assertIn("WantedBy=multi-user.target", unit)
        self.assertIn("Type=oneshot", unit)
        self.assertIn("StateDirectory=dpms-boot-events", unit)
        self.assertNotIn("docker", unit)
        self.assertNotIn("network-online.target", unit)


if __name__ == "__main__":
    unittest.main()
