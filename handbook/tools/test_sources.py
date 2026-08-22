"""Tests for the source readers: the layer that turns repo files into facts.

Every reader is tested twice — once against a synthetic tree (so the
assertions are exact and stable), once against this repo (so the reader
fails loudly when it stops finding anything, rather than rendering an
empty chapter that looks fine).
"""

import json
import unittest
from pathlib import Path
from textwrap import dedent

import sources

REPO = Path(__file__).resolve().parents[2]


def write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).lstrip("\n"), encoding="utf-8")


class CrateReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        write(self.root, "core/crates/alpha/Cargo.toml", '[package]\nname = "alpha"\n')
        write(self.root, "core/crates/alpha/src/lib.rs", "//! Does the alpha thing.\n//! Second line.\n\npub mod x;\n")
        write(self.root, "core/crates/beta/Cargo.toml", '[package]\nname = "beta"\n')
        write(self.root, "core/crates/beta/src/lib.rs", "pub mod y;\n")
        write(self.root, "core/shared/gamma/Cargo.toml", '[package]\nname = "gamma"\n')
        write(self.root, "core/shared/gamma/src/lib.rs", "//! Shared gamma.\n")
        write(
            self.root,
            "core/shared/app/src/registry.rs",
            'pub const MOUNTED_CRATES: &[&str] = &[\n    "alpha",\n];\n',
        )

    def test_reads_plugin_and_shared_crates_with_their_tier(self):
        crates = sources.collect_crates(self.root)
        self.assertEqual(
            [(c.name, c.tier) for c in crates],
            [("alpha", "plugin"), ("beta", "plugin"), ("gamma", "shared")],
        )

    def test_module_doc_becomes_the_summary_joined_into_one_paragraph(self):
        alpha = sources.crate_by_name(sources.collect_crates(self.root), "alpha")
        self.assertEqual(alpha.doc, "Does the alpha thing. Second line.")

    def test_a_crate_without_a_module_doc_reports_an_empty_summary(self):
        beta = sources.crate_by_name(sources.collect_crates(self.root), "beta")
        self.assertEqual(beta.doc, "")

    def test_mounted_flag_comes_from_the_registry_seam(self):
        crates = {c.name: c.mounted for c in sources.collect_crates(self.root)}
        self.assertEqual(crates, {"alpha": True, "beta": False, "gamma": False})

    def test_this_repo_has_every_mounted_crate_present_on_disk(self):
        crates = sources.collect_crates(REPO)
        mounted = [c.name for c in crates if c.mounted]
        self.assertEqual(len(mounted), 9, "MOUNTED_CRATES lists nine plugin crates")
        self.assertGreaterEqual(len(crates), 15)


class RouteReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        schema = {
            "paths": {
                "/api/b": {"post": {"tags": ["beta"], "summary": "Make Beta"}},
                "/api/a": {
                    "get": {"tags": ["alpha"], "summary": "Read Alpha"},
                    "delete": {"summary": "Drop Alpha"},
                },
            }
        }
        write(self.root, "packages/api-client/openapi.json", json.dumps(schema))

    def test_routes_are_sorted_by_path_then_method(self):
        routes = sources.collect_routes(self.root)
        self.assertEqual(
            [(r.path, r.method) for r in routes],
            [("/api/a", "DELETE"), ("/api/a", "GET"), ("/api/b", "POST")],
        )

    def test_a_route_without_tags_is_grouped_as_untagged(self):
        routes = {(r.path, r.method): r.tag for r in sources.collect_routes(self.root)}
        self.assertEqual(routes[("/api/a", "DELETE")], "untagged")

    def test_this_repo_serves_the_documented_number_of_paths(self):
        # Counted from `packages/api-client/openapi.json`, which is generated
        # from the service. So this asserts two things at once: how many paths
        # there are, and that the generated client has been regenerated since
        # they changed. It caught the second — the client sat at 42 while the
        # service served 46, missing among others the engagement's meetings
        # list that the toolbar picker calls.
        routes = sources.collect_routes(REPO)
        self.assertEqual(len({r.path for r in routes}), 49)


class EnvVarReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        write(
            self.root,
            ".env.example",
            """
            # Preamble that belongs to no section.

            # ── First section ──────────────────
            # REQUIRED (the service). What it is.
            THING_KEY=placeholder

            # OPTIONAL — only when you want it.
            # THING_OPT=1

            # ── Second section ─────────────────
            # REQUIRED. Another one.
            OTHER=x
            """,
        )

    def test_variables_carry_their_section_heading(self):
        found = {v.name: v.section for v in sources.collect_env_vars(self.root)}
        self.assertEqual(
            found,
            {
                "THING_KEY": "First section",
                "THING_OPT": "First section",
                "OTHER": "Second section",
            },
        )

    def test_required_is_read_from_the_preceding_comment_block(self):
        found = {v.name: v.required for v in sources.collect_env_vars(self.root)}
        self.assertEqual(found, {"THING_KEY": True, "THING_OPT": False, "OTHER": True})

    def test_commented_out_variables_are_still_collected(self):
        names = [v.name for v in sources.collect_env_vars(self.root)]
        self.assertIn("THING_OPT", names)

    def test_summary_is_the_comment_block_without_the_required_marker(self):
        found = {v.name: v.summary for v in sources.collect_env_vars(self.root)}
        self.assertEqual(found["THING_KEY"], "What it is.")
        self.assertEqual(found["THING_OPT"], "only when you want it.")

    def test_a_marker_carries_to_later_variables_in_the_same_section(self):
        # `.env.example` writes one "OPTIONAL — all default if unset." above a
        # run of five model aliases. Read literally, only the first is marked;
        # read the way a person reads it, all five are.
        write(
            self.root,
            ".env.example",
            """
            # ── Aliases ────────────────────────
            # OPTIONAL — all default if unset.
            # FIRST=a
            # SECOND=b

            # ── Other ──────────────────────────
            # THIRD=c
            """,
        )
        markers = {v.name: v.marker for v in sources.collect_env_vars(self.root)}
        self.assertEqual(markers, {"FIRST": "optional", "SECOND": "optional",
                                   "THIRD": "unmarked"})

    def test_a_variable_with_its_own_marker_overrides_the_section_marker(self):
        write(
            self.root,
            ".env.example",
            """
            # ── Mixed ──────────────────────────
            # OPTIONAL — mostly.
            # FIRST=a
            # REQUIRED. Except this one.
            SECOND=b
            # THIRD=c
            """,
        )
        markers = {v.name: v.marker for v in sources.collect_env_vars(self.root)}
        self.assertEqual(markers["FIRST"], "optional")
        self.assertEqual(markers["SECOND"], "required")
        self.assertEqual(markers["THIRD"], "required")

    def test_a_variable_with_neither_marker_is_reported_as_unmarked(self):
        write(
            self.root,
            ".env.example",
            """
            # ── Only section ───────────────────
            # Just a description, no marker at all.
            UNMARKED=x
            """,
        )
        var = sources.collect_env_vars(self.root)[0]
        self.assertEqual(var.marker, "unmarked")
        self.assertFalse(var.required)

    def test_a_marked_variable_records_which_marker_it_carried(self):
        markers = {v.name: v.marker for v in sources.collect_env_vars(self.root)}
        self.assertEqual(
            markers,
            {"THING_KEY": "required", "THING_OPT": "optional", "OTHER": "required"},
        )

    def test_this_repo_still_has_env_variables_carrying_no_marker(self):
        # .env.example's own preamble promises every variable is marked
        # REQUIRED or OPTIONAL. Several are not. The handbook shows the gap
        # rather than filing them under a marker they do not carry.
        #
        # Asserted as "some remain" rather than by name: this used to pin
        # `DATABASE_URL`, which has since been marked OPTIONAL and commented
        # out — a variable being fixed should not fail the guard that noticed
        # it was broken. When the list finally empties, this test is the one to
        # invert, because at that point the preamble is telling the truth.
        unmarked = [v.name for v in sources.collect_env_vars(REPO) if v.marker == "unmarked"]
        self.assertTrue(unmarked, "every variable is marked now — invert this guard")
        self.assertNotIn("DATABASE_URL", unmarked)

    def test_this_repo_declares_both_required_and_optional_variables(self):
        env = sources.collect_env_vars(REPO)
        self.assertGreaterEqual(len(env), 25)
        self.assertTrue(any(v.required for v in env))
        self.assertTrue(any(not v.required for v in env))


class ComponentReaderTest(unittest.TestCase):
    def test_service_modules_skip_dunder_and_cache_directories(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "apps/service/src/app/modules/__init__.py", "")
            write(root, "apps/service/src/app/modules/__pycache__/x.pyc", "")
            write(root, "apps/service/src/app/modules/nudges/__init__.py", "")
            write(root, "apps/service/src/app/modules/slow-lane/router.py", "")
            names = [m.name for m in sources.collect_service_modules(root)]
            self.assertEqual(names, ["nudges", "slow-lane"])

    def test_a_hyphenated_module_is_flagged_as_import_module_only(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "apps/service/src/app/modules/slow-lane/router.py", "")
            write(root, "apps/service/src/app/modules/nudges/router.py", "")
            flags = {m.name: m.importable for m in sources.collect_service_modules(root)}
            self.assertEqual(flags, {"nudges": True, "slow-lane": False})

    def test_a_module_without_an_init_is_flagged_as_invisible_to_pkgutil(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "apps/service/src/app/modules/seen/__init__.py", "")
            write(root, "apps/service/src/app/modules/unseen/router.py", "")
            flags = {m.name: m.is_package for m in sources.collect_service_modules(root)}
            self.assertEqual(flags, {"seen": True, "unseen": False})

    def test_build_output_does_not_inflate_a_component_file_count(self):
        # Otherwise a `pytest` run makes the chapter stale and CI fails on a
        # change nobody made.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "apps/service/src/app/modules/thing/router.py", "")
            before = sources.collect_service_modules(root)[0].files
            write(root, "apps/service/src/app/modules/thing/__pycache__/router.pyc", "x")
            write(root, "apps/service/src/app/modules/thing/.pytest_cache/v/x", "x")
            self.assertEqual(sources.collect_service_modules(root)[0].files, before)

    def test_this_repo_exposes_its_service_modules_and_desktop_features(self):
        self.assertGreaterEqual(len(sources.collect_service_modules(REPO)), 9)
        self.assertGreaterEqual(len(sources.collect_desktop_features(REPO)), 8)


class ReadinessReaderTest(unittest.TestCase):
    """Each journey document ends with an honest status table. Those are
    the most useful thing in the whole set for somebody deciding whether to
    rely on a feature, so they are collected into a chapter of their own."""

    JOURNEY = """
        # 3. Catch a vague answer

        Some prose.

        ## Where this stands

        | | |
        |---|---|
        | ✅ Ready | The whole panel and all four responses |
        | ⏳ Not yet | A native speaker still has to review the word list |
        | ⚙️ Setup | Needs a provider configured first |
        """

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        write(self.root, "docs/journeys/03-catch.md", self.JOURNEY)

    def test_the_area_comes_from_the_heading_without_its_number(self):
        notes = sources.collect_readiness(self.root)
        self.assertTrue(notes)
        self.assertEqual(notes[0].area, "Catch a vague answer")

    def test_each_row_of_the_status_table_becomes_a_note(self):
        self.assertEqual(len(sources.collect_readiness(self.root)), 3)

    def test_the_marker_is_turned_into_a_state_rather_than_kept_as_a_symbol(self):
        states = [n.state for n in sources.collect_readiness(self.root)]
        self.assertEqual(states, ["working", "planned", "setup"])

    def test_the_note_text_survives_intact(self):
        notes = sources.collect_readiness(self.root)
        self.assertEqual(notes[0].note, "The whole panel and all four responses")

    def test_no_emoji_reaches_the_collected_notes(self):
        for note in sources.collect_readiness(self.root):
            self.assertNotIn("\u2705", note.note + note.state + note.area)
            self.assertNotIn("\u23f3", note.note + note.state + note.area)

    def test_prose_before_the_status_section_is_ignored(self):
        notes = sources.collect_readiness(self.root)
        self.assertFalse(any("Some prose" in n.note for n in notes))

    def test_a_marker_nobody_recognises_is_reported_rather_than_dropped(self):
        # A row marked with an emoji that is not one of the three reads exactly
        # like a row that was collected, and disappears from the handbook
        # without anything saying so. That happened: a "not yet" row written
        # with a different construction emoji vanished from the generated
        # chapter, and the only signal was the row not being there.
        write(self.root, "docs/journeys/05-odd.md", """
            # 5. Odd

            ## Where this stands

            | | |
            |---|---|
            | \U0001f6a7 Not yet | The connector nobody has built |
            """)
        unknown = sources.unknown_status_markers(self.root)
        self.assertEqual(len(unknown), 1)
        self.assertIn("05-odd.md", unknown[0].document)
        self.assertIn("\U0001f6a7", unknown[0].marker)

    def test_the_recognised_markers_are_not_reported_as_unknown(self):
        self.assertEqual(sources.unknown_status_markers(self.root), [])

    def test_a_journey_with_no_status_table_contributes_nothing(self):
        write(self.root, "docs/journeys/04-empty.md", "# 4. Nothing\n\nJust prose.\n")
        areas = {n.area for n in sources.collect_readiness(self.root)}
        self.assertNotIn("Nothing", areas)

    def test_the_readme_is_not_treated_as_a_journey(self):
        write(self.root, "docs/journeys/README.md",
              "# How Elicta is used\n\n## Where this stands\n\n| | |\n|---|---|\n| ✅ Ready | x |\n")
        areas = {n.area for n in sources.collect_readiness(self.root)}
        self.assertNotIn("How Elicta is used", areas)

    def test_this_repo_has_readiness_notes_in_both_states(self):
        notes = sources.collect_readiness(REPO)
        self.assertGreaterEqual(len(notes), 20)
        self.assertTrue(any(n.state == "working" for n in notes))
        self.assertTrue(any(n.state == "planned" for n in notes))


class CommandReaderTest(unittest.TestCase):
    def test_command_title_comes_from_the_first_heading(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".claude/commands/do-it.md", "# Do The Thing\n\nRuns it.\nMore.\n")
            commands = sources.collect_commands(root)
            self.assertEqual([(c.name, c.title, c.summary) for c in commands],
                             [("do-it", "Do The Thing", "Runs it.")])

    def test_this_repo_ships_its_slash_commands(self):
        names = [c.name for c in sources.collect_commands(REPO)]
        self.assertIn("handbook-sync", names)


if __name__ == "__main__":
    unittest.main()
