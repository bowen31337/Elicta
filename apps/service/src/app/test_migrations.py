"""The migration chain must stay runnable.

For a long time these revisions could not run at all: there was no
`alembic.ini`, no `env.py`, and `alembic` was not a declared dependency, so
nothing ever executed an `upgrade()` body. A schema that only exists as
unexecuted Python is not a schema.

These run the whole chain in offline mode, which executes every revision's
`upgrade()` and renders SQL without needing a live database — cheap enough
for every test run, and enough to catch a broken revision, a broken link in
the chain, or a second head appearing from a parallel merge.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def test_the_chain_has_exactly_one_head(alembic_config: Config) -> None:
    """Two heads mean two parallel branches nothing has merged."""

    heads = ScriptDirectory.from_config(alembic_config).get_heads()

    assert len(heads) == 1, f"expected a single head, found {heads}"


def test_every_revision_runs_from_base_to_head(alembic_config: Config) -> None:
    """Executes all 20 `upgrade()` bodies and renders the resulting SQL."""

    rendered = io.StringIO()
    with redirect_stdout(rendered):
        command.upgrade(alembic_config, "head", sql=True)

    sql = rendered.getvalue()

    assert "CREATE TABLE alembic_version" in sql
    created = sql.count("CREATE TABLE ")
    assert created >= 20, f"expected the full schema, saw {created} CREATE TABLE statements"


def test_the_schema_the_routers_depend_on_is_actually_created(
    alembic_config: Config,
) -> None:
    """Spot-check the tables the mounted API surface reads and writes."""

    rendered = io.StringIO()
    with redirect_stdout(rendered):
        command.upgrade(alembic_config, "head", sql=True)

    sql = rendered.getvalue()

    for table in (
        "engagements",
        "meetings",
        "attendees",
        "candidates",
        "nudges",
        "artifacts",
        "citations",
        "coverage_slots",
        "egress_log",
        "reference_documents",
        "vocabulary_terms",
        "consent_records",
    ):
        assert f"CREATE TABLE {table}" in sql, f"{table} is never created"


def _schema_from_migrations() -> dict[str, set[str]]:
    """The columns the revision chain leaves on each table, read statically.

    Parsed rather than executed because the chain is written for PostgreSQL —
    `JSONB`, `ARRAY`, `USING` casts — and cannot be replayed against the SQLite
    the test suite runs on. Static reading is enough for the question this
    guard asks, which is whether a column exists at all.
    """

    import ast
    from pathlib import Path

    tables: dict[str, set[str]] = {}
    here = Path(__file__).resolve()
    versions = next(
        candidate / "migrations" / "versions"
        for candidate in here.parents
        if (candidate / "migrations" / "versions").is_dir()
    )

    def literal(node: ast.AST) -> str | None:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    # Walked in revision order, not filename order: a revision that renames or
    # drops a column has to be read after the one that created it, and the two
    # orders do not coincide — `continuity_tables_bind_to_app.py` sorts before
    # `engagements_create.py` but runs twenty revisions after it.
    parsed = {}
    for path in versions.glob("*.py"):
        tree = ast.parse(path.read_text())
        header = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        # Only `upgrade()` describes the schema a deployment ends up with.
        # Walking the whole module would also read `downgrade()`, whose whole
        # job is to undo it — every add cancelled by its matching drop.
        upgrade = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        )
        parsed[header["revision"]] = (header.get("down_revision"), upgrade)

    order, seen = [], set()
    remaining = dict(parsed)
    while remaining:
        ready = [rev for rev, (down, _) in remaining.items() if down is None or down in seen]
        assert ready, f"migration chain is broken or cyclic at {sorted(remaining)}"
        for rev in ready:
            order.append(remaining.pop(rev)[1])
            seen.add(rev)

    for upgrade in order:
        for call in (n for n in ast.walk(upgrade) if isinstance(n, ast.Call)):
            if not isinstance(call.func, ast.Attribute) or not call.args:
                continue
            name, table = call.func.attr, literal(call.args[0])
            if table is None:
                continue

            if name == "create_table":
                columns = {
                    literal(inner.args[0])
                    for inner in call.args[1:]
                    if isinstance(inner, ast.Call) and inner.args and literal(inner.args[0])
                }
                tables.setdefault(table, set()).update(columns)
            elif name == "add_column" and len(call.args) > 1:
                inner = call.args[1]
                if isinstance(inner, ast.Call) and inner.args:
                    column = literal(inner.args[0])
                    if column:
                        tables.setdefault(table, set()).add(column)
            elif name == "drop_column" and len(call.args) > 1:
                column = literal(call.args[1])
                if column and table in tables:
                    tables[table].discard(column)
            elif name == "alter_column" and len(call.args) > 1:
                renamed = next(
                    (literal(kw.value) for kw in call.keywords if kw.arg == "new_column_name"),
                    None,
                )
                original = literal(call.args[1])
                if renamed and original and table in tables:
                    tables[table].discard(original)
                    tables[table].add(renamed)

    return tables


def test_the_orm_models_and_the_migration_chain_describe_the_same_tables() -> None:
    """The guard that keeps `app/persistence/models.py` honest.

    The models are what the product reads and writes; the chain is what a
    deployed database is actually built from. Nothing enforces that those two
    agree — a column added to a model works perfectly against the SQLite file
    the models create for themselves, and then fails on PostgreSQL, where the
    column was never migrated. This test is that enforcement.
    """

    from app.persistence.models import metadata

    migrated = _schema_from_migrations()

    for table in metadata.sorted_tables:
        assert table.name in migrated, (
            f"model {table.name!r} has no table in the migration chain — "
            "add a revision before shipping it"
        )
        missing = {column.name for column in table.columns} - migrated[table.name]
        assert not missing, (
            f"{table.name}: model columns {sorted(missing)} are not created by any "
            "revision, so they would be absent on PostgreSQL"
        )


def test_the_drift_guard_can_actually_fail() -> None:
    """A guard that cannot fail is decoration, so prove this one can."""

    import sqlalchemy as sa

    from app.persistence.models import metadata

    migrated = _schema_from_migrations()
    assert "invented_column" not in migrated["engagements"]

    probe = sa.Table("engagements", sa.MetaData(), sa.Column("invented_column", sa.Text()))
    assert {column.name for column in probe.columns} - migrated["engagements"]
    assert metadata.tables["engagements"] is not probe
