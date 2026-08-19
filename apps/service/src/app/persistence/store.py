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

import json
import os
import threading
from collections.abc import Callable, Iterator, MutableMapping
from pathlib import Path
from typing import Any, TypeVar

import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from .models import metadata

K = TypeVar("K")
V = TypeVar("V")

DEFAULT_STATE_DIR = Path.home() / ".elicta"
DEFAULT_DB_NAME = "state.db"


def default_database_url() -> str:
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
    return engine


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
            connection.execute(sa.delete(table).where(table.c[key_column] == key))
            if rows:
                connection.execute(sa.insert(table), rows)

    # -- the five continuity collections ---------------------------------

    def engagements(self, decode: Callable[[dict[str, Any]], V]) -> DurableMapping[str, V]:
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
            forget=lambda key: self._delete(table, "id", key),
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
            forget=lambda key: self._delete(table, "id", key),
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

    def meeting_details(self, decode: Callable[[dict[str, Any]], V]) -> DurableMapping[str, V]:
        """The assembled meeting read-model, keyed by meeting id."""

        table = metadata.tables["meetings"]
        loaded = {
            row.id: decode(row.detail) for row in self._rows(table) if row.detail is not None
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
            forget=lambda key: self._delete(table, "id", key),
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
