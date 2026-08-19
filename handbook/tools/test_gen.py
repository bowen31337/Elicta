"""End-to-end tests for the generator CLI, over a synthetic repository.

These are the tests that matter most, because they pin the two contracts
the whole scheme rests on: `build` is reproducible, and `check` fails when
the code moved and the handbook did not.
"""

import io
import contextlib
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

import gen

MANIFEST = """
[handbook]
title = "Test Handbook"
intro = "A handbook for a test repository."

[[chapter]]
id = "intro"
file = "chapters/01-intro.md"
title = "Introduction"
kind = "prose"
summary = "Why any of this exists."
watches = ["core/crates"]

[[chapter]]
id = "crates"
file = "chapters/02-crates.md"
title = "Crate Reference"
kind = "generated"
generator = "crates"
summary = "Every crate, from the manifests."
"""


class GenTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.write("handbook/book.toml", MANIFEST)
        self.write("core/crates/alpha/Cargo.toml", '[package]\nname = "alpha"\n')
        self.write("core/crates/alpha/src/lib.rs", "//! The alpha crate.\n")
        self.write("core/shared/app/src/registry.rs",
                   'pub const MOUNTED_CRATES: &[&str] = &[\n    "alpha",\n];\n')

    def write(self, rel: str, body: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(body).lstrip("\n"), encoding="utf-8")
        return path

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = gen.main([*argv, "--root", str(self.root)])
        return code, out.getvalue()


class BuildTest(GenTestCase):
    def test_build_writes_the_generated_chapter_from_the_real_sources(self):
        self.run_cli("build")
        page = self.read("handbook/chapters/02-crates.md")
        self.assertIn("# Crate Reference", page)
        self.assertIn("`alpha`", page)
        self.assertIn("The alpha crate.", page)

    def test_build_scaffolds_a_prose_chapter_that_does_not_exist_yet(self):
        self.run_cli("build")
        page = self.read("handbook/chapters/01-intro.md")
        self.assertIn("# Introduction", page)
        self.assertIn(gen.STUB_MARKER, page)

    def test_build_writes_an_index_linking_every_chapter(self):
        self.run_cli("build")
        index = self.read("handbook/index.md")
        self.assertIn("chapters/01-intro.md", index)
        self.assertIn("chapters/02-crates.md", index)
        self.assertIn("Test Handbook", index)

    def test_building_twice_produces_byte_identical_output(self):
        self.run_cli("build")
        first = {p: p.read_bytes() for p in (self.root / "handbook").rglob("*.md")}
        self.run_cli("build")
        second = {p: p.read_bytes() for p in (self.root / "handbook").rglob("*.md")}
        self.assertEqual(first, second)

    def test_build_never_rewrites_prose_above_the_nav_marker(self):
        self.run_cli("build")
        self.write("handbook/chapters/01-intro.md", "# Introduction\n\nCarefully written.\n")
        self.run_cli("build")
        page = self.read("handbook/chapters/01-intro.md")
        self.assertIn("Carefully written.", page)
        self.assertNotIn(gen.STUB_MARKER, page)

    def test_build_adds_navigation_linking_neighbouring_chapters(self):
        self.run_cli("build")
        self.assertIn("02-crates.md", self.read("handbook/chapters/01-intro.md"))
        self.assertIn("01-intro.md", self.read("handbook/chapters/02-crates.md"))

    def test_build_does_not_baseline_drift_on_its_own(self):
        self.run_cli("build")
        self.assertFalse((self.root / "handbook" / "drift.lock.json").exists())


class CheckTest(GenTestCase):
    def green(self):
        self.run_cli("build")
        self.run_cli("accept", "--all")

    def test_a_freshly_built_handbook_checks_clean(self):
        self.green()
        code, out = self.run_cli("check")
        self.assertEqual(code, 0, out)

    def test_a_new_crate_makes_the_generated_chapter_stale(self):
        self.green()
        self.write("core/crates/beta/Cargo.toml", '[package]\nname = "beta"\n')
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("stale-generated", out)

    def test_rebuilding_after_a_new_crate_clears_the_staleness(self):
        self.green()
        self.write("core/crates/beta/Cargo.toml", '[package]\nname = "beta"\n')
        self.run_cli("build")
        code, out = self.run_cli("check")
        self.assertNotIn("stale-generated", out)

    def test_a_new_crate_puts_the_watching_prose_chapter_into_drift(self):
        self.green()
        self.write("core/crates/beta/Cargo.toml", '[package]\nname = "beta"\n')
        self.run_cli("build")
        _, out = self.run_cli("check")
        self.assertIn("drifted", out)
        self.assertIn("intro", out)

    def test_drift_alone_is_a_warning_and_does_not_fail_the_build(self):
        self.green()
        self.write("core/crates/beta/Cargo.toml", '[package]\nname = "beta"\n')
        self.run_cli("build")
        code, _ = self.run_cli("check")
        self.assertEqual(code, 0)

    def test_strict_mode_turns_drift_into_a_failure(self):
        self.green()
        self.write("core/crates/beta/Cargo.toml", '[package]\nname = "beta"\n')
        self.run_cli("build")
        code, _ = self.run_cli("check", "--strict")
        self.assertEqual(code, 1)

    def test_a_deleted_chapter_file_is_reported_as_missing(self):
        self.green()
        (self.root / "handbook" / "chapters" / "01-intro.md").unlink()
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("missing-page", out)

    def test_a_markdown_file_absent_from_the_manifest_is_reported_as_an_orphan(self):
        self.green()
        self.write("handbook/chapters/99-stray.md", "# Stray\n")
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("orphan-page", out)

    def test_a_hand_edited_generated_chapter_is_reported_as_stale(self):
        self.green()
        path = self.root / "handbook" / "chapters" / "02-crates.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSnuck in.\n", encoding="utf-8")
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("stale-generated", out)

    def test_a_stub_chapter_is_reported_so_it_cannot_ship_unnoticed(self):
        self.run_cli("build")
        _, out = self.run_cli("check")
        self.assertIn("stub-page", out)

    def test_check_names_the_command_that_fixes_a_stale_chapter(self):
        self.green()
        self.write("core/crates/beta/Cargo.toml", '[package]\nname = "beta"\n')
        _, out = self.run_cli("check")
        self.assertIn("gen.py build", out)


class PdfTest(GenTestCase):
    """The whole handbook as one PDF, keyed on a digest of its sources."""

    @property
    def pdf_path(self):
        return self.root / "handbook" / gen.PDF_NAME

    def test_build_writes_one_pdf_for_the_whole_handbook(self):
        self.run_cli("build")
        self.assertTrue(self.pdf_path.is_file())
        self.assertTrue(self.pdf_path.read_bytes().startswith(b"%PDF-"))

    def test_the_pdf_carries_the_digest_of_the_sources_it_was_built_from(self):
        self.run_cli("build")
        self.assertEqual(gen.embedded_digest(self.pdf_path),
                         gen.pdf_source_digest(self.root))

    def test_a_second_build_leaves_the_pdf_untouched(self):
        # Otherwise every CI run rewrites a binary and the "produces no
        # diff" gate fails on a change nobody made.
        self.run_cli("build")
        before = self.pdf_path.read_bytes()
        self.run_cli("build")
        self.assertEqual(self.pdf_path.read_bytes(), before)

    def test_editing_a_chapter_makes_the_pdf_stale(self):
        self.run_cli("build")
        self.run_cli("accept", "--all")
        path = self.root / "handbook" / "chapters" / "01-intro.md"
        path.write_text("# Introduction\n\nRewritten by hand.\n", encoding="utf-8")
        # Deliberately no rebuild: `build` is what fixes this, so running it
        # here would test nothing.
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("stale-pdf", out)

    def test_rebuilding_clears_the_staleness(self):
        self.run_cli("build")
        self.run_cli("accept", "--all")
        path = self.root / "handbook" / "chapters" / "01-intro.md"
        path.write_text("# Introduction\n\nRewritten by hand.\n", encoding="utf-8")
        self.run_cli("build")
        self.run_cli("pdf")
        code, out = self.run_cli("check")
        self.assertNotIn("stale-pdf", out)
        self.assertEqual(code, 0, out)

    def test_a_deleted_pdf_is_reported_as_missing(self):
        self.run_cli("build")
        self.run_cli("accept", "--all")
        self.pdf_path.unlink()
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("missing-pdf", out)

    def test_the_pdf_subcommand_rebuilds_on_demand_and_reports_its_size(self):
        self.run_cli("build")
        code, out = self.run_cli("pdf")
        self.assertEqual(code, 0)
        self.assertIn("pages", out)

    def test_the_digest_moves_when_a_chapter_moves(self):
        before = gen.pdf_source_digest(self.root)
        self.write("handbook/chapters/01-intro.md", "# Introduction\n\nNew words.\n")
        self.assertNotEqual(before, gen.pdf_source_digest(self.root))

    def test_the_digest_covers_the_rendering_code_as_well_as_the_chapters(self):
        # A change to the typesetter changes the document, so it has to
        # change the digest, or the committed PDF silently keeps the old
        # layout for ever.
        self.assertIn("typeset.py", gen.PDF_TOOL_SOURCES)
        self.assertIn("pdf.py", gen.PDF_TOOL_SOURCES)
        self.assertIn("mdread.py", gen.PDF_TOOL_SOURCES)


class AcceptTest(GenTestCase):
    def test_accepting_one_chapter_records_only_that_chapter(self):
        self.run_cli("build")
        code, _ = self.run_cli("accept", "--chapter", "intro")
        self.assertEqual(code, 0)
        import json
        lock = json.loads(self.read("handbook/drift.lock.json"))
        self.assertEqual(list(lock), ["intro"])

    def test_accepting_an_unknown_chapter_fails_loudly(self):
        self.run_cli("build")
        code, out = self.run_cli("accept", "--chapter", "nope")
        self.assertEqual(code, 1)
        self.assertIn("nope", out)

    def test_accept_requires_naming_a_chapter_or_asking_for_all(self):
        code, out = self.run_cli("accept")
        self.assertEqual(code, 1)
        self.assertIn("--chapter", out)


class StatusTest(GenTestCase):
    def test_status_lists_every_chapter_with_its_kind(self):
        self.run_cli("build")
        code, out = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("intro", out)
        self.assertIn("crates", out)
        self.assertIn("generated", out)

    def test_status_reports_the_drift_state_of_each_prose_chapter(self):
        self.run_cli("build")
        _, out = self.run_cli("status")
        self.assertIn("unbaselined", out)


class GeneratorRegistryTest(unittest.TestCase):
    """This repository's characteristic failure is a component that is
    built, tested, and wired to nothing. A generator that no chapter uses
    must therefore be a stated decision rather than a discovery."""

    def test_every_generator_is_either_used_or_declared_unused(self):
        import book as bookmod
        import generators

        repo = Path(__file__).resolve().parents[2]
        mounted = {c.generator for c in bookmod.load_book(repo).chapters if c.generator}
        for name in generators.GENERATORS:
            self.assertTrue(
                name in mounted or name in generators.UNMOUNTED,
                f"generator {name!r} is in neither book.toml nor UNMOUNTED",
            )

    def test_nothing_is_both_used_and_declared_unused(self):
        import book as bookmod
        import generators

        repo = Path(__file__).resolve().parents[2]
        mounted = {c.generator for c in bookmod.load_book(repo).chapters if c.generator}
        self.assertEqual(mounted & set(generators.UNMOUNTED), set())

    def test_every_declared_unused_generator_gives_a_reason(self):
        import generators

        for name, reason in generators.UNMOUNTED.items():
            self.assertGreater(len(reason.strip()), 20, name)

    def test_declaring_a_generator_unused_does_not_let_a_typo_through(self):
        import generators

        for name in generators.UNMOUNTED:
            self.assertIn(name, generators.GENERATORS,
                          f"{name!r} is declared unused but does not exist")


class RealRepoTest(unittest.TestCase):
    """The handbook in this repository must itself be clean."""

    def test_this_repos_handbook_builds_and_checks_without_errors(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = gen.main(["check"])
        self.assertEqual(code, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
