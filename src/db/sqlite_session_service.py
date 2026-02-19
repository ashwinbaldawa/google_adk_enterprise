"""
SQLite Session Service for Google ADK.

Same enterprise features as Postgres version but using SQLite.
Uses synchronous sqlite3 (ADK's async calls work via asyncio.to_thread).
"""

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Optional

from google.adk.events.event import Event
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.session import Session

from .sqlite_connection import get_connection, init_db

logger = logging.getLogger(__name__)


class SQLiteSessionService(BaseSessionService):
    """Enterprise session service using SQLite."""

    def __init__(self, tenant_id: str, agent_name: str = "", model_used: str = ""):
        self._tenant_id = tenant_id
        self._agent_name = agent_name
        self._model_used = model_used
        init_db()
        logger.info("SQLite session service ready | tenant=%s", tenant_id)

    @classmethod
    async def create(
        cls, tenant_id: str, agent_name: str = "", model_used: str = "",
        **kwargs,
    ) -> "SQLiteSessionService":
        """Factory method (matches Postgres interface)."""
        return cls(tenant_id, agent_name, model_used)

    async def close(self):
        """No-op for SQLite (no pool to close)."""
        logger.info("SQLite session service closed.")

    def _conn(self) -> sqlite3.Connection:
        return get_connection()

    # ----------------------------------------------------------------
    # ADK BaseSessionService
    # ----------------------------------------------------------------

    async def create_session(
        self, *, app_name: str, user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        session_id = session_id or str(uuid.uuid4())
        state = state or {}
        now = time.time()

        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO sessions (session_id, app_name, user_id, tenant_id, agent_name, model_used) VALUES (?,?,?,?,?,?)",
                (session_id, app_name, user_id, self._tenant_id, self._agent_name, self._model_used),
            )
            if state:
                self._upsert_state(conn, app_name, user_id, session_id, state)
            self._audit(conn, user_id, "session_created", "session", session_id)
            conn.commit()
        finally:
            conn.close()

        logger.info("Created session %s | tenant=%s", session_id, self._tenant_id)
        return Session(id=session_id, app_name=app_name, user_id=user_id,
                       state=state, events=[], last_update_time=now)

    async def get_session(
        self, *, app_name: str, user_id: str, session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT session_id, app_name, user_id, updated_at FROM sessions WHERE app_name=? AND user_id=? AND session_id=? AND tenant_id=?",
                (app_name, user_id, session_id, self._tenant_id),
            ).fetchone()

            if not row:
                return None

            state = self._load_state(conn, app_name, user_id, session_id)
            events = self._load_events(conn, app_name, user_id, session_id, config)
        finally:
            conn.close()

        return Session(
            id=row["session_id"], app_name=row["app_name"], user_id=row["user_id"],
            state=state, events=events, last_update_time=time.time(),
        )

    async def list_sessions(self, *, app_name: str, user_id: str) -> ListSessionsResponse:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT session_id, app_name, user_id, updated_at FROM sessions WHERE app_name=? AND user_id=? AND tenant_id=? ORDER BY updated_at DESC",
                (app_name, user_id, self._tenant_id),
            ).fetchall()
        finally:
            conn.close()

        return ListSessionsResponse(sessions=[
            Session(id=r["session_id"], app_name=r["app_name"], user_id=r["user_id"],
                    state={}, events=[], last_update_time=time.time())
            for r in rows
        ])

    async def delete_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "DELETE FROM sessions WHERE app_name=? AND user_id=? AND session_id=? AND tenant_id=?",
                (app_name, user_id, session_id, self._tenant_id),
            )
            self._audit(conn, user_id, "session_deleted", "session", session_id)
            conn.commit()
        finally:
            conn.close()
        logger.info("Deleted session %s", session_id)

    async def append_event(self, session: Session, event: Event) -> Event:
        event = await super().append_event(session, event)
        if event.partial:
            return event

        start_time = time.time()
        conn = self._conn()
        try:
            event_id = event.id or str(uuid.uuid4())
            event_data = json.loads(event.model_dump_json(exclude_none=True))

            event_type = "message"
            if event.actions and event.actions.state_delta:
                event_type = "state_change"

            conn.execute(
                """INSERT OR IGNORE INTO session_events
                   (event_id, app_name, user_id, session_id, invocation_id, author, event_type, event_data, model_used)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (event_id, session.app_name, session.user_id, session.id,
                 event.invocation_id or "", event.author or "unknown",
                 event_type, json.dumps(event_data), self._model_used),
            )

            # Update session timestamp
            conn.execute(
                "UPDATE sessions SET updated_at=datetime('now') WHERE app_name=? AND user_id=? AND session_id=?",
                (session.app_name, session.user_id, session.id),
            )

            if event.actions and event.actions.state_delta:
                self._upsert_state(conn, session.app_name, session.user_id,
                                   session.id, event.actions.state_delta)

            latency_ms = int((time.time() - start_time) * 1000)
            if event.author and event.author != "user":
                self._track_usage(conn, session.user_id, session.id, event_id,
                                  session.app_name, latency_ms)

            conn.commit()
        finally:
            conn.close()

        return event

    # ----------------------------------------------------------------
    # Enterprise: Feedback
    # ----------------------------------------------------------------

    async def add_feedback(
        self, app_name: str, user_id: str, session_id: str,
        event_id: str, rating: int, feedback_type: str = "general",
        comment: str = "",
    ):
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO event_feedback
                   (feedback_id, app_name, user_id, session_id, event_id, tenant_id, rating, feedback_type, comment)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (user_id, event_id) DO UPDATE SET rating=?, comment=?""",
                (str(uuid.uuid4()), app_name, user_id, session_id, event_id,
                 self._tenant_id, rating, feedback_type, comment,
                 rating, comment),
            )
            conn.commit()
        finally:
            conn.close()

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------

    def _track_usage(self, conn, user_id, session_id, event_id, app_name, latency_ms):
        conn.execute(
            """INSERT INTO usage_tracking
               (usage_id, tenant_id, user_id, session_id, event_id, app_name, model_used, latency_ms)
               VALUES (?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), self._tenant_id, user_id, session_id, event_id,
             app_name, self._model_used or "unknown", latency_ms),
        )

    def _audit(self, conn, user_id, action, resource_type, resource_id, details=None):
        conn.execute(
            """INSERT INTO audit_log
               (log_id, tenant_id, user_id, action, resource_type, resource_id, details)
               VALUES (?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), self._tenant_id, user_id, action,
             resource_type, resource_id, json.dumps(details or {})),
        )

    def _upsert_state(self, conn, app_name, user_id, session_id, state_delta):
        for key, value in state_delta.items():
            if key.startswith("temp:"):
                continue
            conn.execute(
                """INSERT INTO session_state (app_name, user_id, session_id, state_key, state_value, updated_by)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT (app_name, user_id, session_id, state_key)
                   DO UPDATE SET state_value=?, updated_by=?, updated_at=datetime('now')""",
                (app_name, user_id, session_id, key, json.dumps(value), user_id,
                 json.dumps(value), user_id),
            )

    def _load_state(self, conn, app_name, user_id, session_id):
        rows = conn.execute(
            "SELECT state_key, state_value FROM session_state WHERE app_name=? AND user_id=? AND session_id=?",
            (app_name, user_id, session_id),
        ).fetchall()
        return {r["state_key"]: json.loads(r["state_value"]) for r in rows}

    def _load_events(self, conn, app_name, user_id, session_id, config=None):
        if config and config.num_recent_events is not None:
            rows = conn.execute(
                """SELECT event_data FROM (
                     SELECT event_data, sequence_num FROM session_events
                     WHERE app_name=? AND user_id=? AND session_id=?
                     ORDER BY sequence_num DESC LIMIT ?
                   ) sub ORDER BY sequence_num ASC""",
                (app_name, user_id, session_id, config.num_recent_events),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT event_data FROM session_events WHERE app_name=? AND user_id=? AND session_id=? ORDER BY sequence_num ASC",
                (app_name, user_id, session_id),
            ).fetchall()

        events = []
        for r in rows:
            try:
                d = json.loads(r["event_data"])
                events.append(Event.model_validate(d))
            except Exception as e:
                logger.warning("Failed to deserialize event: %s", e)
        return events
