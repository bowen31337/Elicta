use rusqlite::{Connection, Result as SqlResult};

/// Creates the on-device bank schema if it doesn't already exist, and turns
/// on foreign-key enforcement so deleting a meeting's bank row cascades to
/// its candidates and their trigger-type/requires rows — a resync never
/// leaves an orphaned candidate from the meeting's previous compile behind.
pub fn ensure_schema(conn: &Connection) -> SqlResult<()> {
    conn.pragma_update(None, "foreign_keys", "ON")?;

    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS meeting_banks (
            meeting_id   TEXT PRIMARY KEY,
            generated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bank_candidates (
            meeting_id                    TEXT NOT NULL
                                           REFERENCES meeting_banks(meeting_id)
                                           ON DELETE CASCADE,
            id                            TEXT NOT NULL,
            template_section              TEXT NOT NULL,
            phrasing                      TEXT NOT NULL,
            stub                          TEXT NOT NULL,
            lang                          TEXT NOT NULL,
            priority                      INTEGER NOT NULL,
            authority_match               REAL NOT NULL,
            source_doc                    TEXT,
            embedding                     BLOB NOT NULL,
            inherited_from_open_question  INTEGER NOT NULL,
            PRIMARY KEY (meeting_id, id)
        );

        CREATE INDEX IF NOT EXISTS bank_candidates_meeting_id
            ON bank_candidates(meeting_id);

        CREATE TABLE IF NOT EXISTS bank_candidate_trigger_types (
            meeting_id    TEXT NOT NULL,
            candidate_id  TEXT NOT NULL,
            position      INTEGER NOT NULL,
            trigger_type  TEXT NOT NULL,
            FOREIGN KEY (meeting_id, candidate_id)
                REFERENCES bank_candidates(meeting_id, id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS bank_candidate_trigger_types_candidate_id
            ON bank_candidate_trigger_types(meeting_id, candidate_id);

        CREATE TABLE IF NOT EXISTS bank_candidate_requires (
            meeting_id    TEXT NOT NULL,
            candidate_id  TEXT NOT NULL,
            position      INTEGER NOT NULL,
            requirement   TEXT NOT NULL,
            FOREIGN KEY (meeting_id, candidate_id)
                REFERENCES bank_candidates(meeting_id, id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS bank_candidate_requires_candidate_id
            ON bank_candidate_requires(meeting_id, candidate_id);
        ",
    )
}
