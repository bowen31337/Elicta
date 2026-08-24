"""Write-through durable collections for the engagement-continuity state.

Every router in this service reaches persistence through a plain `dict` or
`list` field on `Backend`, injected as a closure. That is a good seam and this
module does not disturb it: the collections below satisfy the same
`MutableMapping` protocol, so a router that did `backend.engagements[eid] = x`
keeps working unchanged and simply gains durability.

**Why write-through, and why synchronous.** Writes land in the database inside
the same call that mutates the dict, so there is no window in which the
operator has been told something was saved and it was not. The alternative —
scheduling the write on the event loop — would return sooner but lose the last
few operations on a crash, which is precisely the failure this work exists to
remove. The cost is a sub-millisecond SQLite write on the request path, and a
read is never more than a dict lookup because the whole working set is loaded
into memory at startup. Engagement state is small and bounded by how many
meetings a consultancy runs; if that ever stops being true, the reads are
already behind a mapping and can become queries without touching a router.

**SQLite by default, PostgreSQL when asked.** The desktop product ships a
single-user service with no database server, so the default is a file beside
the settings database. Setting `DATABASE_URL` points the same code at the
PostgreSQL deployment the migration chain targets.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from collections.abc import Callable, Iterator, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from .models import metadata

K = TypeVar("K")
V = TypeVar("V")

DEFAULT_STATE_DIR = Path.home() / ".elicta"
DEFAULT_DB_NAME = "state.db"


def default_database_url() -> str:  # noqa: D401 - kept for callers that predate resolve
    """Where state lives when nothing says otherwise.

    `DATABASE_URL` wins, so a deployment can point at PostgreSQL without a
    code change. Otherwise a file under `ELICTA_STATE_DIR` (or `~/.elicta`),
    which is the same place the settings database and its key already live.
    """

    configured = os.environ.get("DATABASE_URL")
    if configured:
        # The migration chain is written for asyncpg; these collections are
        # synchronous, so strip the async driver marker if one is present.
        return configured.replace("+asyncpg", "").replace("+aiosqlite", "")

    state_dir = Path(os.environ.get("ELICTA_STATE_DIR") or DEFAULT_STATE_DIR)
    state_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{state_dir / DEFAULT_DB_NAME}"


def resolve_database_url(configured: str | None = None) -> str:
    """Which database this deployment keeps its state in.

    The order is the one every other setting here follows: a value somebody
    chose beats a fallback. `configured` comes from the settings store, so an
    operator can move a deployment onto PostgreSQL from the Settings screen;
    `DATABASE_URL` remains the headless route; and with neither, state lives in
    a SQLite file, because the desktop product ships to people who have no
    database server and should not need one.

    Changing it takes effect on restart, not immediately: the collections are
    opened once, at startup, and bound into the `Backend` the app is built
    with.
    """

    chosen = (configured or "").strip() or os.environ.get("DATABASE_URL") or ""
    if chosen:
        # The migration chain is written for asyncpg; these collections are
        # synchronous, so strip the async driver marker if one is present.
        return chosen.replace("+asyncpg", "").replace("+aiosqlite", "")

    state_dir = Path(os.environ.get("ELICTA_STATE_DIR") or DEFAULT_STATE_DIR)
    state_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{state_dir / DEFAULT_DB_NAME}"


def redact_database_url(url: str) -> str:
    """A database URL safe to show back, with any password removed.

    A PostgreSQL URL embeds its password, so this is a credential and the
    settings API never returns one of those. It is still worth showing which
    server a deployment is pointed at, so the host, user and database survive
    and only the password goes. Anything that will not parse is described
    rather than echoed, since an unparseable string may still contain one.
    """

    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "(unreadable)"
    if not parts.scheme:
        return "(unreadable)"
    if parts.password is None:
        return url

    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    user = f"{parts.username}@" if parts.username else ""
    return urlunsplit((parts.scheme, f"{user}{host}", parts.path, parts.query, parts.fragment))


def create_state_engine(url: str | None = None) -> Engine:
    """An engine for the state database, with the tables created if absent.

    `check_same_thread=False` because uvicorn serves requests from a worker
    thread pool and the connection is guarded by this module's own lock; the
    SQLite driver's own thread check would reject the second thread to arrive
    even though the access is already serialised.
    """

    resolved = url or default_database_url()
    connect_args = {"check_same_thread": False} if resolved.startswith("sqlite") else {}
    engine = create_engine(resolved, connect_args=connect_args, future=True)
    metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine


def _add_missing_columns(engine: Engine) -> None:
    """Catch an existing database up with columns the models have gained.

    `metadata.create_all` creates missing *tables* and never missing *columns*,
    so adding one to a model left every existing `state.db` failing on its
    first query with the operator's engagements still in the file, unreadable.
    Alembic covers the PostgreSQL deployment; the file the desktop product
    makes for itself has no migration step to run, so it catches up here.

    Deliberately additive only: this exists to stop an upgrade losing data,
    and a schema fixer that can drop or retype a column is a much more
    dangerous thing than the problem it solves.
    """

    inspector = sa.inspect(engine)
    for table in metadata.tables.values():
        if not inspector.has_table(table.name):
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            filling = _backfill_clause(column, engine.dialect)
            if filling is None:
                continue
            kind = column.type.compile(engine.dialect)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}{filling}'
                    )
                )


def _backfill_clause(column: sa.Column, dialect: Any) -> str | None:
    """What to fill this column with for the rows that predate it, or `None` to skip it.

    A nullable column needs nothing: the rows already there read as `NULL`,
    which the column allows. A `NOT NULL` column needs a default or the
    `ALTER` is refused outright -- every existing row would violate the
    constraint the moment it arrived -- and this used to skip those entirely,
    which meant the one kind of column that could brick an existing file was
    the one kind the repair would not touch.

    Compiled against the dialect rather than written out, because the same
    `sa.false()` is `0` on SQLite and `false` on PostgreSQL. A `NOT NULL`
    column with no default is still skipped: there is no answer for the
    existing rows, and inventing one is exactly the dangerous repair above.
    """

    if column.nullable:
        return ""
    if column.server_default is None:
        return None
    literal = column.server_default.arg
    if not isinstance(literal, str):
        literal = literal.compile(dialect=dialect).string
    return f" NOT NULL DEFAULT {literal}"


def _enum_text(value: Any) -> str:
    """The stored form of a status column.

    `TranscriptionStatus` and friends are `str`-valued enums, but `str()` on
    one renders `TranscriptionStatus.COMPLETE` rather than `complete`, which
    reads back as an invalid value. Taking `.value` is the difference between
    a row that decodes and one that raises on the next start.
    """

    return str(getattr(value, "value", value))


def _refuse_to_forget(key: Any) -> None:
    """The `forget` for a collection nothing may delete from."""

    raise PermissionError(f"consent records are an audit trail; {key!r} cannot be deleted")


class DurableMapping(MutableMapping[K, V]):
    """A dict whose mutations are written through to a table as they happen.

    Reads are served from memory. Writes go to both, under a lock, in that
    order — so a failed write raises before the in-memory copy diverges from
    what is on disk, rather than after.
    """

    def __init__(
        self,
        *,
        loaded: dict[K, V],
        persist: Callable[[K, V], None],
        forget: Callable[[K], None],
        lock: threading.Lock,
    ) -> None:
        self._items = loaded
        self._persist = persist
        self._forget = forget
        self._lock = lock

    def __getitem__(self, key: K) -> V:
        return self._items[key]

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            self._persist(key, value)
            self._items[key] = value

    def __delitem__(self, key: K) -> None:
        with self._lock:
            self._forget(key)
            del self._items[key]

    def __iter__(self) -> Iterator[K]:
        return iter(dict(self._items))

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"DurableMapping({self._items!r})"


def _json_default(value: Any) -> Any:
    """Serialise the datetimes and enums Pydantic models carry."""

    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"cannot serialise {type(value).__name__}")


def dump(model: Any) -> Any:
    """A JSON-safe representation of a Pydantic model or plain value."""

    if hasattr(model, "model_dump"):
        return json.loads(json.dumps(model.model_dump(), default=_json_default))
    return json.loads(json.dumps(model, default=_json_default))


class StateStore:
    """Opens the durable collections that back `Backend`'s continuity fields.

    Each accessor reads the table once, builds the in-memory image the routers
    will hit, and returns a mapping that writes any later change straight back.
    Constructing the store is therefore the only place that touches the
    database on a read path.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    @property
    def engine(self) -> Engine:
        return self._engine

    def close(self) -> None:
        self._engine.dispose()

    def _rows(self, table: sa.Table) -> list[sa.Row]:
        with self._engine.connect() as connection:
            return list(connection.execute(sa.select(table)))

    def _upsert(self, table: sa.Table, key_column: str, key: Any, values: dict[str, Any]) -> None:
        with self._engine.begin() as connection:
            existing = connection.execute(
                sa.select(table.c[key_column]).where(table.c[key_column] == key)
            ).first()
            if existing is None:
                connection.execute(sa.insert(table).values(**{key_column: key}, **values))
            else:
                connection.execute(
                    sa.update(table).where(table.c[key_column] == key).values(**values)
                )

    def _delete(self, table: sa.Table, key_column: str, key: Any) -> None:
        with self._engine.begin() as connection:
            connection.execute(sa.delete(table).where(table.c[key_column] == key))

    def soft_delete(self, table_name: str, key: str) -> bool:
        """Mark one row deleted. Returns whether there was a live row to mark."""

        table = metadata.tables[table_name]
        # Deliberately does not take `self._lock`. This is reached as a
        # `DurableMapping`'s `forget`, which already holds that lock, and
        # `threading.Lock` is not reentrant — taking it here deadlocked the
        # process rather than raising. The write is one transaction, and the
        # in-memory half the lock guards belongs to the caller.
        with self._engine.begin() as connection:
            marked = connection.execute(
                table.update()
                .where(table.c.id == key)
                .where(table.c.deleted_at.is_(None))
                .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
            )
            return bool(marked.rowcount)

    def _replace_children(
        self, table: sa.Table, key_column: str, key: Any, rows: list[dict[str, Any]]
    ) -> None:
        """Rewrite the whole child set for one parent.

        A candidate bank or an open-questions list is always handed over whole
        by the code that produces it, so a diff would be invented complexity —
        and a delete-then-insert in one transaction cannot leave a half-updated
        list behind the way an incremental merge can.
        """

        with self._engine.begin() as connection:
            removal = sa.delete(table).where(table.c[key_column] == key)
            if "deleted_at" in table.c:
                # A soft-deleted row has to survive the next rewrite of its
                # list, or the mark lasts exactly one write: delete a document,
                # upload another, and the deleted one is erased on the way past.
                removal = removal.where(table.c.deleted_at.is_(None))
            connection.execute(removal)
            if rows:
                connection.execute(sa.insert(table), rows)

    # -- the five continuity collections ---------------------------------

    def engagements(self, decode: Callable[[dict[str, Any]], V]) -> DurableMapping[str, V]:  # noqa: D401
        """Engagement client context, keyed by engagement id (FR-3.1)."""

        table = metadata.tables["engagements"]
        loaded = {
            row.id: decode(
                {
                    "client_organisation": row.client_name,
                    "sector": row.sector,
                    "commercial_context": row.commercial_context,
                }
            )
            for row in self._rows(table)
            if row.deleted_at is None
        }

        def persist(key: str, value: Any) -> None:
            payload = dump(value)
            self._upsert(
                table,
                "id",
                key,
                {
                    "client_name": payload.get("client_organisation", ""),
                    "sector": payload.get("sector", ""),
                    "commercial_context": payload.get("commercial_context", ""),
                },
            )

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            # Marked, not erased: `del backend.engagements[id]` is how the
            # product removes one, and it should stay recoverable.
            forget=lambda key: self.soft_delete("engagements", key),
            lock=self._lock,
        )

    def expected_languages(self) -> DurableMapping[str, list[str]]:
        """The languages an engagement expects in the room (FR-2.14).

        The same `engagements` row the two collections above read, and the
        column has been in the schema since its first revision — it was simply
        never written. Derived once, when the engagement is created, and never
        recomputed, so holding it in memory meant the panel's language strip
        went quiet for every existing engagement after a restart.
        """

        table = metadata.tables["engagements"]
        loaded: dict[str, list[str]] = {
            row.id: list(row.expected_languages or [])
            for row in self._rows(table)
            if row.deleted_at is None and row.expected_languages
        }

        def persist(key: str, value: Any) -> None:
            # Accepts the model the deriver returns or a plain list, because
            # the composition root holds one and the row stores the other.
            languages = list(getattr(value, "languages", None) or value or [])
            self._upsert(table, "id", key, {"expected_languages": languages})

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self.soft_delete("engagements", key),
            lock=self._lock,
        )

    def engagement_updates(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, V]:
        """The mutable engagement fields — purpose, scope, template (FR-3.5).

        Deliberately the same row as `engagements()`: an engagement is one
        record, split across two `Backend` fields only because the create and
        update routes were built against different shapes. Both accessors
        write their own columns, so neither clobbers the other.
        """

        table = metadata.tables["engagements"]
        loaded = {
            row.id: decode(
                {
                    "engagement_id": row.id,
                    "purpose": row.purpose or None,
                    "scope_boundary": row.scope_boundary or None,
                    "target_requirements_template": row.template_id or None,
                }
            )
            for row in self._rows(table)
            if row.deleted_at is None
        }

        def persist(key: str, value: Any) -> None:
            payload = dump(value)
            self._upsert(
                table,
                "id",
                key,
                {
                    "purpose": payload.get("purpose") or "",
                    "scope_boundary": payload.get("scope_boundary") or "",
                    "template_id": payload.get("target_requirements_template") or "",
                },
            )

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            # The same row `engagements()` reads, so the same soft mark: a
            # hard delete here would erase a record the other view only hid.
            forget=lambda key: self.soft_delete("engagements", key),
            lock=self._lock,
        )

    def highest_engagement_ordinal(self) -> int:
        """The largest `eng-N` suffix on record, or 0 for an empty database.

        The id counter is derived rather than stored, so it cannot drift out of
        step with the rows it names: a stored counter that failed to persist
        once would go on minting ids that already exist, and the collision
        would surface as one engagement quietly overwriting another.
        """

        table = metadata.tables["engagements"]
        ordinals = [
            int(row.id.removeprefix("eng-"))
            for row in self._rows(table)
            if row.id.startswith("eng-") and row.id.removeprefix("eng-").isdigit()
        ]
        return max(ordinals, default=0)

    def highest_meeting_ordinal(self) -> int:
        """The largest `meeting-N` suffix on record, or 0 for an empty database.

        Counts every row, **including the soft-deleted ones**, for the reason
        `highest_document_ordinal` gives: `meetings.id` is a primary key, and a
        marked row is still holding its id. Derived from the loaded mapping
        instead, this would walk backwards the moment a meeting was removed —
        delete the only meeting, restart, create another, and it would be
        issued `meeting-1` against a row the table still has.
        """

        table = metadata.tables["meetings"]
        ordinals = [
            int(row.id.removeprefix("meeting-"))
            for row in self._rows(table)
            if row.id.startswith("meeting-") and row.id.removeprefix("meeting-").isdigit()
        ]
        return max(ordinals, default=0)

    def highest_linked_document_ordinal(self) -> int:
        """The largest `reference-document-N` suffix on record, or 0.

        `reference_documents` carries two id schemes, because it has two
        intake paths: an upload is `doc-N` and a link is
        `reference-document-N`, and FR-3.2 keeps the link's id rather than
        minting a second one for the list. They cannot collide with each
        other, so they are counted apart — this reads only its own prefix, and
        `highest_document_ordinal` only reads the other.

        The failure it prevents is quieter than the vocabulary one and worse
        to find. `document_texts` persists by updating the row with that id
        and inserting only when nothing matched, so a reissued
        `reference-document-1` does not raise: it finds the earlier row and
        writes over its text. One engagement's attached document becomes
        another's, and nothing reports anything.

        Soft-deleted rows count, for the reason `highest_document_ordinal`
        gives: the row is still holding its id.
        """

        table = metadata.tables["reference_documents"]
        prefix = "reference-document-"
        ordinals = [
            int(row.id.removeprefix(prefix))
            for row in self._rows(table)
            if row.id.startswith(prefix) and row.id.removeprefix(prefix).isdigit()
        ]
        return max(ordinals, default=0)

    def highest_vocabulary_term_ordinal(self) -> int:
        """The largest `term-N` suffix on record, or 0 for an empty database.

        Vocabulary was moved onto the store because nothing rebuilds what
        somebody typed, and the counter that mints its ids was left behind on
        `Backend`, starting at 0 every time the process does. The consequence
        is the one `highest_document_ordinal` describes, and it was found in
        the field rather than reasoned about: a service holding `term-1`
        through `term-18` answered 500 to every word an operator tried to add,
        `UNIQUE constraint failed: vocabulary_terms.id`, while the list beside
        the box stayed empty.

        Soft-deleted rows count. A removed term keeps its id — `deleted_at` is
        a mark, not an erasure — so a counter derived from what loaded would
        hand back an id the table is still holding.
        """

        table = metadata.tables["vocabulary_terms"]
        ordinals = [
            int(row.id.removeprefix("term-"))
            for row in self._rows(table)
            if row.id.startswith("term-") and row.id.removeprefix("term-").isdigit()
        ]
        return max(ordinals, default=0)

    def highest_document_ordinal(self) -> int:
        """The largest `doc-N` suffix on record, or 0 for an empty database.

        Derived the same way, and for a sharper reason than engagements.
        `reference_documents.id` is a primary key, so a re-minted id is not a
        quiet overwrite — it is a `UNIQUE constraint` failure that reaches the
        operator as "The service answered 500" on the first document they
        attach after a restart.

        Every row counts, including the soft-deleted ones and the text-first
        writes with no engagement yet. `reference_documents` skips both when it
        loads, so a counter derived from what loaded would hand back an id the
        table is still holding.
        """

        table = metadata.tables["reference_documents"]
        ordinals = [
            int(row.id.removeprefix("doc-"))
            for row in self._rows(table)
            if row.id.startswith("doc-") and row.id.removeprefix("doc-").isdigit()
        ]
        return max(ordinals, default=0)

    def meeting_details(self, decode: Callable[[dict[str, Any]], V]) -> DurableMapping[str, V]:
        """The assembled meeting read-model, keyed by meeting id."""

        table = metadata.tables["meetings"]
        loaded = {
            row.id: decode(row.detail)
            for row in self._rows(table)
            if row.detail is not None and row.deleted_at is None
        }

        def persist(key: str, value: Any) -> None:
            payload = dump(value)
            self._upsert(
                table,
                "id",
                key,
                {
                    "engagement_id": payload.get("engagement_id", ""),
                    "state": payload.get("state", "scheduled"),
                    "capture_mode": payload.get("capture_mode", "monolingual"),
                    "detail": payload,
                },
            )

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            # Marked, not erased — the same choice `engagements` makes, and for
            # a stronger reason: the id is what a consent record, a record-path
            # transcript and an audio-destruction event all point at. Erasing
            # the row would also lower the high-water mark `next_meeting_id` is
            # derived from, and the next launch would mint an id that is not
            # free.
            forget=lambda key: self.soft_delete("meetings", key),
            lock=self._lock,
        )

    def meeting_updates(self, decode: Callable[[dict[str, Any]], V]) -> DurableMapping[str, V]:
        """What an operator typed about a meeting: its purpose and target sections (FR-3.8).

        Durable because nothing rebuilds it. The purpose is a sentence a person
        wrote on the Preparation screen; it is not derived from the audio, the
        template or the engagement, so a restart that dropped it would be
        losing the only copy — the same test `record_path_artifacts` failed.

        Its own collection rather than a field on `meeting_details` because the
        two are written by different routes at different times, and the
        `meetings` table has carried the `purpose` and `target_sections`
        columns for this since it was created. `_upsert` keys on the row that
        `meeting_details` already wrote, so the two never race to create it.
        """

        table = metadata.tables["meetings"]
        loaded = {
            row.id: decode(
                {
                    "meeting_id": row.id,
                    "session_purpose": row.purpose or None,
                    "target_template_sections": row.target_sections or None,
                }
            )
            for row in self._rows(table)
            # An untouched meeting has neither, and decoding one would put an
            # all-`None` update in the map that reads as "somebody set this".
            if row.deleted_at is None and (row.purpose or row.target_sections)
        }

        def persist(key: str, value: Any) -> None:
            payload = dump(value)
            self._upsert(
                table,
                "id",
                key,
                {
                    "purpose": payload.get("session_purpose") or "",
                    "target_sections": payload.get("target_template_sections") or [],
                },
            )

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            # The meeting's removal is recorded once, by `meeting_details`'s
            # forget, on this same row. Marking it again here would be a second
            # record of one decision, and clearing the columns instead would
            # destroy the purpose a soft delete promises to keep.
            forget=lambda key: self.soft_delete("meetings", key),
            lock=self._lock,
        )

    def requirements_state(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, V]:
        """The standing requirements state, one row per engagement (FR-8.9)."""

        table = metadata.tables["requirements_state"]
        loaded = {
            row.engagement_id: decode(
                {
                    "engagement_id": row.engagement_id,
                    "confirmed_requirements": row.confirmed_requirements,
                    "contradictions": row.contradictions,
                    "decisions": row.decisions,
                    "updated_at": row.updated_at,
                }
            )
            for row in self._rows(table)
        }

        def persist(key: str, value: Any) -> None:
            payload = dump(value)
            self._upsert(
                table,
                "engagement_id",
                key,
                {
                    "confirmed_requirements": payload.get("confirmed_requirements", []),
                    "contradictions": payload.get("contradictions", []),
                    "decisions": payload.get("decisions", []),
                },
            )

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "engagement_id", key),
            lock=self._lock,
        )

    def open_questions(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, list[V]]:
        """Open questions carried onto an engagement, ranked by impact (FR-4.8)."""

        table = metadata.tables["open_questions"]
        loaded: dict[str, list[V]] = {}
        for row in sorted(self._rows(table), key=lambda r: (r.engagement_id, r.impact_rank)):
            loaded.setdefault(row.engagement_id, []).append(
                decode({"text": row.text, "impact_rank": row.impact_rank})
            )

        def persist(key: str, value: Any) -> None:
            rows = [
                {
                    "engagement_id": key,
                    "text": item["text"],
                    "impact_rank": item["impact_rank"],
                }
                for item in (dump(entry) for entry in value)
            ]
            self._replace_children(table, "engagement_id", key, rows)

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "engagement_id", key),
            lock=self._lock,
        )

    def reference_documents(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, list[V]]:
        """An engagement's attached documents, in the order they were added."""

        table = metadata.tables["reference_documents"]
        loaded: dict[str, list[V]] = {}
        for row in sorted(self._rows(table), key=lambda r: (r.engagement_id, r.ordinal)):
            # A row with no engagement is a text-first write whose list has not
            # landed yet; it carries the content but not the name the list is
            # keyed on, and decoding it would fail validation on an empty name.
            if not row.engagement_id or row.deleted_at is not None:
                continue
            loaded.setdefault(row.engagement_id, []).append(
                decode({"document_id": row.id, "name": row.name, "status": row.status})
            )

        def persist(key: str, value: Any) -> None:
            existing = {
                row.id: row
                for row in self._rows(table)
                if row.engagement_id == key
            }
            rows = [
                {
                    "id": item["document_id"],
                    "engagement_id": key,
                    "name": item["name"],
                    "status": item["status"],
                    # Carried through rather than recomputed: the text was
                    # extracted once on intake, and the row is rewritten
                    # whenever any document in the list changes — a retag must
                    # not silently blank the content the compiler reads.
                    "source_uri": getattr(existing.get(item["document_id"]), "source_uri", "") or "",
                    "extracted_text": getattr(
                        existing.get(item["document_id"]), "extracted_text", ""
                    )
                    or "",
                    "ordinal": ordinal,
                }
                for ordinal, item in enumerate(dump(entry) for entry in value)
            ]
            self._replace_children(table, "engagement_id", key, rows)

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "engagement_id", key),
            lock=self._lock,
        )

    def consent_records(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, list[V]]:
        """Every consent confirmation for a meeting, oldest first.

        Keyed by meeting id and holding the whole list rather than the latest,
        because the list *is* the audit trail: a re-confirmation after a late
        arrival does not replace the earlier one, it follows it. The screen
        shows the last; an audit reads them all.
        """

        table = metadata.tables["consent_records"]
        loaded: dict[str, list[V]] = {}
        for row in sorted(self._rows(table), key=lambda r: (r.meeting_id, r.ordinal)):
            loaded.setdefault(row.meeting_id, []).append(
                decode(
                    {
                        "meeting_id": row.meeting_id,
                        "confirmed_by": row.confirmed_by,
                        # Pydantic parses the ISO-8601 text back, offset and
                        # all, which is why it was stored as text.
                        "confirmed_at": row.confirmed_at,
                    }
                )
            )

        def persist(key: str, value: Any) -> None:
            # Read off the model rather than through `dump`, which would be a
            # second serialisation of a value that is already exactly what the
            # column wants.
            rows = [
                {
                    "id": f"{key}:{ordinal}",
                    "meeting_id": key,
                    "confirmed_by": entry.confirmed_by,
                    "confirmed_at": entry.confirmed_at.isoformat(),
                    "ordinal": ordinal,
                }
                for ordinal, entry in enumerate(value)
            ]
            self._replace_children(table, "meeting_id", key, rows)

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            # A consent record is not withdrawable, so deletion is refused
            # rather than quietly dropped: this is the one collection here
            # whose whole purpose is to still be there when someone asks.
            forget=_refuse_to_forget,
            lock=self._lock,
        )

    # -- the record path's own artifacts ----------------------------------
    #
    # These three arrived together, and for one reason: they were classified
    # as pipeline output "rebuilt from the transcript", and two of them *are*
    # the transcript while the third describes audio NFR-2.4 has already
    # destroyed. Nothing rebuilds any of them. A meeting that really was
    # recorded came back after a restart answering 404 on all three reads,
    # which is indistinguishable from a meeting that never happened — and the
    # desktop service runs under `--reload`, so "a restart" meant every save.

    def record_path_transcripts(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, list[V]]:
        """Every engine's transcript for a session, in the order they finished.

        Keyed by session and holding the whole list because that is how the
        record path produces and reads them: FR-2.6 runs two engines over the
        same audio and the pair is the unit of meaning — one transcript alone
        cannot be compared against anything.
        """

        table = metadata.tables["record_path_transcripts"]
        loaded: dict[str, list[V]] = {}
        for row in sorted(self._rows(table), key=lambda r: (r.session_id, r.ordinal)):
            loaded.setdefault(row.session_id, []).append(
                decode(
                    {
                        "session_id": row.session_id,
                        "engine": row.engine,
                        "status": row.status,
                        "segments": row.segments or [],
                        "text": row.text or "",
                        # Pydantic parses the ISO-8601 text back, offset and
                        # all, which is why it was stored as text.
                        "requested_at": row.requested_at,
                        "completed_at": row.completed_at,
                        "error": row.error,
                    }
                )
            )

        def persist(key: str, value: Any) -> None:
            rows = [
                {
                    "id": f"{key}:{ordinal}",
                    "session_id": key,
                    "engine": entry.engine,
                    "status": _enum_text(entry.status),
                    "segments": [segment.model_dump() for segment in entry.segments],
                    "text": entry.text,
                    "requested_at": entry.requested_at.isoformat(),
                    "completed_at": entry.completed_at.isoformat(),
                    "error": entry.error,
                    "ordinal": ordinal,
                }
                for ordinal, entry in enumerate(value)
            ]
            self._replace_children(table, "session_id", key, rows)

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "session_id", key),
            lock=self._lock,
        )

    def session_alignments(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, V]:
        """What comparing a session's two transcripts found. One row per session."""

        table = metadata.tables["session_alignments"]
        loaded: dict[str, V] = {
            row.session_id: decode(
                {
                    "session_id": row.session_id,
                    "reference_engine": row.reference_engine,
                    "other_engine": row.other_engine,
                    "spans": row.spans or [],
                    "computed_at": row.computed_at,
                }
            )
            for row in self._rows(table)
        }

        def persist(key: str, value: Any) -> None:
            self._upsert(
                table,
                "session_id",
                key,
                {
                    "reference_engine": value.reference_engine,
                    "other_engine": value.other_engine,
                    "spans": [span.model_dump() for span in value.spans],
                    "computed_at": value.computed_at.isoformat(),
                },
            )

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "session_id", key),
            lock=self._lock,
        )

    def audio_destruction_events(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, list[V]]:
        """Every attempt to destroy a session's raw audio, oldest first.

        Keyed by session rather than kept as one flat log, which is how both
        readers ask about it: "where does this session's audio stand" and "was
        this session's audio destroyed". The flat list they used to scan was
        the same answer at O(every event ever).

        The whole list is kept, not the latest. A retry after a failure says
        where the audio stands now; the pair together says what happened, and
        NFR-2.4 is a control whose evidence is the point.
        """

        table = metadata.tables["audio_destruction_events"]
        loaded: dict[str, list[V]] = {}
        for row in sorted(self._rows(table), key=lambda r: (r.session_id, r.ordinal)):
            loaded.setdefault(row.session_id, []).append(
                decode(
                    {
                        "session_id": row.session_id,
                        "audio_ref": row.audio_ref or "",
                        "status": row.status,
                        "requested_at": row.requested_at,
                        "completed_at": row.completed_at,
                        "error": row.error,
                    }
                )
            )

        def persist(key: str, value: Any) -> None:
            rows = [
                {
                    "id": f"{key}:{ordinal}",
                    "session_id": key,
                    "audio_ref": entry.audio_ref,
                    "status": _enum_text(entry.status),
                    "requested_at": entry.requested_at.isoformat(),
                    "completed_at": entry.completed_at.isoformat(),
                    "error": entry.error,
                    "ordinal": ordinal,
                }
                for ordinal, entry in enumerate(value)
            ]
            self._replace_children(table, "session_id", key, rows)

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "session_id", key),
            lock=self._lock,
        )


    def document_texts(self) -> DurableMapping[str, str]:
        """The text read out of each document, keyed by document id.

        Stored on the document's own row rather than in a table of its own:
        one document, one row, and no way for the two to drift.
        """

        table = metadata.tables["reference_documents"]
        loaded: dict[str, str] = {
            row.id: row.extracted_text or ""
            for row in self._rows(table)
            # A deleted document must stop shaping the questions, not merely
            # stop being listed.
            if row.deleted_at is None
        }

        def persist(key: str, value: Any) -> None:
            with self._engine.begin() as connection:
                updated = connection.execute(
                    table.update().where(table.c.id == key).values(extracted_text=value)
                )
                if updated.rowcount:
                    return
                # The text can arrive before the document is listed, depending
                # on which write the composition root makes first; the row is
                # completed when the list is written.
                connection.execute(
                    table.insert().values(
                        id=key,
                        engagement_id="",
                        name="",
                        status="hypothesis",
                        source_uri="",
                        extracted_text=value,
                        ordinal=0,
                    )
                )

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            # Marked, not erased: removing a document's text is how the product
            # removes the document, and the row stays for an audit.
            forget=lambda key: self.soft_delete("reference_documents", key),
            lock=self._lock,
        )

    def vocabulary_terms(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, list[V]]:
        """An engagement's keyterms, in the order they were added (FR-3.6)."""

        table = metadata.tables["vocabulary_terms"]
        loaded: dict[str, list[V]] = {}
        for row in sorted(self._rows(table), key=lambda r: (r.engagement_id, r.ordinal)):
            if row.deleted_at is not None:
                continue
            loaded.setdefault(row.engagement_id, []).append(
                decode(
                    {
                        "term_id": row.id,
                        "engagement_id": row.engagement_id,
                        "term": row.term,
                        "term_type": row.term_type,
                        "pronunciation_hint": row.pronunciation_hint,
                    }
                )
            )

        def persist(key: str, value: Any) -> None:
            rows = [
                {
                    "id": item["term_id"],
                    "engagement_id": key,
                    "term": item["term"],
                    "term_type": item["term_type"],
                    "pronunciation_hint": item.get("pronunciation_hint"),
                    "ordinal": ordinal,
                }
                for ordinal, item in enumerate(dump(entry) for entry in value)
            ]
            self._replace_children(table, "engagement_id", key, rows)

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "engagement_id", key),
            lock=self._lock,
        )

    def operator_voiceprints(
        self, decode: Callable[[dict[str, Any]], V]
    ) -> DurableMapping[str, V]:
        """The enrolled operator voiceprint, keyed by operator id (FR-1.5).

        The embedding crosses this boundary as base64 rather than as bytes.
        Every durable collection here persists through `dump`, which is JSON,
        and raw bytes do not survive that — so the model carries the encoded
        form and the column underneath stays binary, which is what the table
        was created as and what keeps a 96-byte vector 96 bytes on disk.
        """

        table = metadata.tables["operator_voiceprints"]
        loaded: dict[str, V] = {
            row.operator_id: decode(
                {
                    "operator_id": row.operator_id,
                    "embedding": base64.b64encode(row.embedding).decode("ascii"),
                    "embedding_model": row.embedding_model,
                    "sample_duration_ms": row.sample_duration_ms,
                    "enrolled_at": row.enrolled_at,
                }
            )
            for row in self._rows(table)
        }

        def persist(key: str, value: Any) -> None:
            payload = dump(value)
            self._upsert(
                table,
                "operator_id",
                key,
                {
                    # Keyed by the operator rather than by a fresh id per
                    # write: this is an upsert of the one row that operator is
                    # allowed to have, and minting a new id each time would
                    # collide with the unique index instead of replacing.
                    "id": f"voiceprint-{key}",
                    "embedding": base64.b64decode(payload["embedding"]),
                    "embedding_model": payload["embedding_model"],
                    "sample_duration_ms": payload["sample_duration_ms"],
                    "enrolled_at": payload["enrolled_at"],
                },
            )

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "operator_id", key),
            lock=self._lock,
        )

    def candidates(self, decode: Callable[[dict[str, Any]], V]) -> DurableMapping[str, list[V]]:
        """The compiled candidate bank for an engagement (FR-4.8)."""

        table = metadata.tables["candidates"]
        loaded: dict[str, list[V]] = {}
        for row in sorted(self._rows(table), key=lambda r: (r.engagement_id, r.ordinal)):
            loaded.setdefault(row.engagement_id, []).append(
                decode(
                    {
                        "id": row.id,
                        "template_section": row.template_section,
                        "phrasing": row.phrasing,
                        "priority": row.priority,
                        "inherited_from_open_question": row.inherited_from_open_question,
                        "pruned": row.pruned,
                    }
                )
            )

        def persist(key: str, value: Any) -> None:
            rows = [
                {
                    "id": item["id"],
                    "engagement_id": key,
                    "template_section": item["template_section"],
                    "phrasing": item["phrasing"],
                    "priority": item["priority"],
                    "inherited_from_open_question": item.get(
                        "inherited_from_open_question", False
                    ),
                    "pruned": item.get("pruned", False),
                    "ordinal": ordinal,
                }
                for ordinal, item in enumerate(dump(entry) for entry in value)
            ]
            self._replace_children(table, "engagement_id", key, rows)

        return DurableMapping(
            loaded=loaded,
            persist=persist,
            forget=lambda key: self._delete(table, "engagement_id", key),
            lock=self._lock,
        )


def open_state_store(url: str | None = None) -> StateStore:
    """Open the state database, creating it if this is the first run."""

    return StateStore(create_state_engine(url))
