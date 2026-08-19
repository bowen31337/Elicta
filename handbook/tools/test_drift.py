"""Tests for drift detection.

Drift is the half of the mechanism that covers prose. Generated chapters
are checked by rebuilding them; a hand-written chapter cannot be rebuilt,
so instead each one declares the sources it describes and we record a
digest of those sources. When the digest moves, the chapter is suspect.

The digest must move for every kind of change a feature can make -- edited
content, a new file, a deleted file, a rename -- or the mechanism quietly
stops noticing things.
"""

import tempfile
import unittest
from pathlib import Path

import drift


class DigestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.rs").write_text("fn a() {}\n", encoding="utf-8")
        (self.root / "src" / "b.rs").write_text("fn b() {}\n", encoding="utf-8")

    def digest(self):
        return drift.digest(self.root, ["src"])

    def test_the_same_tree_digests_the_same_way_twice(self):
        self.assertEqual(self.digest(), self.digest())

    def test_editing_a_watched_file_changes_the_digest(self):
        before = self.digest()
        (self.root / "src" / "a.rs").write_text("fn a() { todo!() }\n", encoding="utf-8")
        self.assertNotEqual(before, self.digest())

    def test_adding_a_file_under_a_watched_directory_changes_the_digest(self):
        before = self.digest()
        (self.root / "src" / "c.rs").write_text("fn c() {}\n", encoding="utf-8")
        self.assertNotEqual(before, self.digest())

    def test_deleting_a_watched_file_changes_the_digest(self):
        before = self.digest()
        (self.root / "src" / "b.rs").unlink()
        self.assertNotEqual(before, self.digest())

    def test_renaming_a_file_changes_the_digest_even_though_content_is_equal(self):
        before = self.digest()
        (self.root / "src" / "b.rs").rename(self.root / "src" / "bb.rs")
        self.assertNotEqual(before, self.digest())

    def test_build_output_and_caches_are_ignored_so_the_digest_is_stable(self):
        before = self.digest()
        cache = self.root / "src" / "__pycache__"
        cache.mkdir()
        (cache / "a.pyc").write_bytes(b"\x00\x01")
        self.assertEqual(before, self.digest())

    def test_a_watched_path_that_does_not_exist_digests_without_raising(self):
        self.assertIsInstance(drift.digest(self.root, ["nowhere"]), str)

    def test_a_missing_path_digests_differently_from_an_empty_one(self):
        (self.root / "empty").mkdir()
        self.assertNotEqual(
            drift.digest(self.root, ["nowhere"]), drift.digest(self.root, ["empty"])
        )


class LockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "handbook").mkdir()

    def test_an_absent_lock_reads_as_empty_rather_than_raising(self):
        self.assertEqual(drift.load_lock(self.root), {})

    def test_a_saved_lock_round_trips(self):
        drift.save_lock(self.root, {"intro": "abc"})
        self.assertEqual(drift.load_lock(self.root), {"intro": "abc"})

    def test_the_lock_is_written_sorted_so_diffs_stay_readable(self):
        drift.save_lock(self.root, {"z": "1", "a": "2"})
        text = (self.root / drift.LOCK).read_text(encoding="utf-8")
        self.assertLess(text.index('"a"'), text.index('"z"'))

    def test_the_lock_ends_with_a_newline(self):
        drift.save_lock(self.root, {"a": "1"})
        self.assertTrue((self.root / drift.LOCK).read_text(encoding="utf-8").endswith("\n"))


class ChapterDriftTest(unittest.TestCase):
    class FakeChapter:
        def __init__(self, cid, watches):
            self.id, self.watches = cid, watches

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "handbook").mkdir()
        (self.root / "one.txt").write_text("1", encoding="utf-8")
        (self.root / "two.txt").write_text("2", encoding="utf-8")
        self.chapters = [
            self.FakeChapter("alpha", ["one.txt"]),
            self.FakeChapter("beta", ["two.txt"]),
        ]

    def test_a_chapter_never_baselined_is_reported_as_unbaselined(self):
        report = drift.compare(self.root, self.chapters, {})
        self.assertEqual({r.chapter for r in report if r.state == "unbaselined"},
                         {"alpha", "beta"})

    def test_only_the_chapter_whose_source_moved_is_reported_as_drifted(self):
        lock = drift.baseline(self.root, self.chapters)
        (self.root / "one.txt").write_text("changed", encoding="utf-8")
        report = drift.compare(self.root, self.chapters, lock)
        self.assertEqual([r.chapter for r in report if r.state == "drifted"], ["alpha"])
        self.assertEqual([r.chapter for r in report if r.state == "current"], ["beta"])

    def test_accepting_one_chapter_leaves_the_other_stale(self):
        lock = drift.baseline(self.root, self.chapters)
        (self.root / "one.txt").write_text("changed", encoding="utf-8")
        (self.root / "two.txt").write_text("changed", encoding="utf-8")
        lock = drift.accept(self.root, self.chapters, lock, "alpha")
        report = drift.compare(self.root, self.chapters, lock)
        self.assertEqual([r.chapter for r in report if r.state == "drifted"], ["beta"])

    def test_accepting_an_unknown_chapter_is_an_error_not_a_silent_no_op(self):
        with self.assertRaises(KeyError):
            drift.accept(self.root, self.chapters, {}, "nope")

    def test_a_chapter_watching_nothing_is_never_reported_as_drifted(self):
        chapters = [self.FakeChapter("static", [])]
        report = drift.compare(self.root, chapters, {})
        self.assertEqual([r.state for r in report], ["unwatched"])


if __name__ == "__main__":
    unittest.main()
