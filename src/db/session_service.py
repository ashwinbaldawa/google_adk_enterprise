"""
Enterprise PostgreSQL Session Service for Google ADK.

Multi-tenant session management with usage tracking and audit logging.
Implements ADK's BaseSessionService interface.
"""

import json
import logging
import time
import uuid
from typing import Any, Optional

import asyncpg

from google.adk.events.event import Event
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.session import Session

from .connection import get_dsn

logger = logging.getLogger(__name__)


class PostgresSessionService(BaseSessionService):
    """Enterprise session service with tenant isolation, usage tracking, and audit."""

    def __init__(
        self, pool: asyncpg.Pool, tenant_id: str,
        agent_name: str = "", model_used: str = "",
    ):
        self._pool = pool
        self._tenant_id = tenant_id
        self._agent_name = agent_name
        self._model_used = model_used

    @classmethod
    async def create(
        cls, tenant_id: str, agent_name: str = "", model_used: str = "",
        min_size: int = 2, max_size: int = 10,
    ) -> "PostgresSessionService":
        """Factory method to create a session service with connection pool."""
        pool = await asyncpg.create_pool(
            dsn=get_dsn(), min_size=min_size, max_size=max_size,
        )
        logger.info("PostgreSQL pool created | tenant=%s", tenant_id)
        return cls(pool, tenant_id, agent_name, model_used)

    async def close(self):
        """Close the connection pool."""
        await self._pool.close()
        logger.info("PostgreSQL pool closed.")

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

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO sessions
                       (session_id, app_name, user_id, tenant_id, agent_name, model_used)
                       VALUES ($1, $2, $3, $4::uuid, $5, $6)""",
                    session_id, app_name, user_id,
                    self._tenant_id, self._agent_name, self._model_used,
                )
                if state:
                    await self._upsert_state(conn, app_name, user_id, session_id, state)
                await self._audit(conn, user_id, "session_created", "session", session_id)

        logger.info("Created session %s | tenant=%s", session_id, self._tenant_id)
        return Session(
            id=session_id, app_name=app_name, user_id=user_id,
            state=state, events=[], last_update_time=now,
        )

    async def get_session(
        self, *, app_name: str, user_id: str, session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT session_id, app_name, user_id,
                          EXTRACT(EPOCH FROM updated_at) AS update_time
                   FROM sessions
                   WHERE app_name=$1 AND user_id=$2 AND session_id=$3 AND tenant_id=$4::uuid""",
                app_name, user_id, session_id, self._tenant_id,
            )
            if not row:
                return None
            state = await self._load_state(conn, app_name, user_id, session_id)
            events = await self._load_events(conn, app_name, user_id, session_id, config)

        return Session(
            id=row["session_id"], app_name=row["app_name"], user_id=row["user_id"],
            state=state, events=events, last_update_time=row["update_time"],
        )

    async def list_sessions(self, *, app_name: str, user_id: str) -> ListSessionsResponse:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT session_id, app_name, user_id,
                          EXTRACT(EPOCH FROM updated_at) AS update_time
                   FROM sessions
                   WHERE app_name=$1 AND user_id=$2 AND tenant_id=$3::uuid
                   ORDER BY updated_at DESC""",
                app_name, user_id, self._tenant_id,
            )
        return ListSessionsResponse(sessions=[
            Session(id=r["session_id"], app_name=r["app_name"], user_id=r["user_id"],
                    state={}, events=[], last_update_time=r["update_time"])
            for r in rows
        ])

    async def delete_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """DELETE FROM sessions
                       WHERE app_name=$1 AND user_id=$2 AND session_id=$3 AND tenant_id=$4::uuid""",
                    app_name, user_id, session_id, self._tenant_id,
                )
                await self._audit(conn, user_id, "session_deleted", "session", session_id)
        logger.info("Deleted session %s | tenant=%s", session_id, self._tenant_id)

    async def append_event(self, session: Session, event: Event) -> Event:
        event = await super().append_event(session, event)
        if event.partial:
            return event

        start_time = time.time()

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                event_id = event.id or str(uuid.uuid4())
                event_data = json.loads(event.model_dump_json(exclude_none=True))

                event_type = "message"
                if event.actions and event.actions.state_delta:
                    event_type = "state_change"

                await conn.execute(
                    """INSERT INTO session_events
                       (event_id, app_name, user_id, session_id,
                        invocation_id, author, event_type, event_data, model_used)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)
                       ON CONFLICT (app_name, user_id, session_id, event_id) DO NOTHING""",
                    event_id, session.app_name, session.user_id, session.id,
                    event.invocation_id or "", event.author or "unknown",
                    event_type, json.dumps(event_data), self._model_used,
                )

                if event.actions and event.actions.state_delta:
                    await self._upsert_state(
                        conn, session.app_name, session.user_id,
                        session.id, event.actions.state_delta,
                    )

                latency_ms = int((time.time() - start_time) * 1000)
                if event.author and event.author != "user":
                    await self._track_usage(
                        conn, session.user_id, session.id, event_id,
                        session.app_name, latency_ms,
                    )
        return event

    # ----------------------------------------------------------------
    # Enterprise: Feedback
    # ----------------------------------------------------------------

    async def add_feedback(
        self, app_name: str, user_id: str, session_id: str,
        event_id: str, rating: int, feedback_type: str = "general",
        comment: str = "",
    ):
        """Add user feedback for a specific event."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO event_feedback
                   (app_name, user_id, session_id, event_id,
                    tenant_id, rating, feedback_type, comment)
                   VALUES ($1,$2,$3,$4,$5::uuid,$6,$7,$8)
                   ON CONFLICT (user_id, event_id)
                   DO UPDATE SET rating=$6, comment=$8""",
                app_name, user_id, session_id, event_id,
                self._tenant_id, rating, feedback_type, comment,
            )

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------

    async def _track_usage(self, conn, user_id, session_id, event_id, app_name, latency_ms):
        await conn.execute(
            """INSERT INTO usage_tracking
               (tenant_id, user_id, session_id, event_id, app_name, model_used, latency_ms)
               VALUES ($1::uuid,$2,$3,$4,$5,$6,$7)""",
            self._tenant_id, user_id, session_id, event_id,
            app_name, self._model_used or "unknown", latency_ms,
        )

    async def _audit(self, conn, user_id, action, resource_type, resource_id, details=None):
        await conn.execute(
            """INSERT INTO audit_log
               (tenant_id, user_id, action, resource_type, resource_id, details)
               VALUES ($1::uuid,$2,$3,$4,$5,$6::jsonb)""",
            self._tenant_id, user_id, action, resource_type, resource_id,
            json.dumps(details or {}),
        )

    async def _upsert_state(self, conn, app_name, user_id, session_id, state_delta):
        for key, value in state_delta.items():
            if key.startswith("temp:"):
                continue
            await conn.execute(
                """INSERT INTO session_state
                   (app_name, user_id, session_id, state_key, state_value, updated_by)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6)
                   ON CONFLICT (app_name, user_id, session_id, state_key)
                   DO UPDATE SET state_value=$5::jsonb, updated_by=$6, updated_at=NOW()""",
                app_name, user_id, session_id, key, json.dumps(value), user_id,
            )

    async def _load_state(self, conn, app_name, user_id, session_id):
        rows = await conn.fetch(
            "SELECT state_key, state_value FROM session_state WHERE app_name=$1 AND user_id=$2 AND session_id=$3",
            app_name, user_id, session_id,
        )
        return {r["state_key"]: (json.loads(r["state_value"]) if isinstance(r["state_value"], str) else r["state_value"]) for r in rows}

    async def _load_events(self, conn, app_name, user_id, session_id, config=None):
        if config and config.num_recent_events is not None:
            query = """SELECT event_data FROM (
                         SELECT event_data, sequence_num FROM session_events
                         WHERE app_name=$1 AND user_id=$2 AND session_id=$3
                         ORDER BY sequence_num DESC LIMIT $4
                       ) sub ORDER BY sequence_num ASC"""
            rows = await conn.fetch(query, app_name, user_id, session_id, config.num_recent_events)
        else:
            rows = await conn.fetch(
                "SELECT event_data FROM session_events WHERE app_name=$1 AND user_id=$2 AND session_id=$3 ORDER BY sequence_num ASC",
                app_name, user_id, session_id,
            )
        events = []
        for r in rows:
            try:
                d = r["event_data"]
                if isinstance(d, str):
                    d = json.loads(d)
                events.append(Event.model_validate(d))
            except Exception as e:
                logger.warning("Failed to deserialize event: %s", e)
        return events
