"""SQLite database connection and schema management."""

import os
import sqlite3
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("SQLITE_DB_PATH", "adk_enterprise.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id       TEXT PRIMARY KEY,
    tenant_name     TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    settings        TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tenant_users (
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user',
    display_name    TEXT,
    email           TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    preferences     TEXT DEFAULT '{}',
    last_active_at  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT NOT NULL,
    app_name        TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    title           TEXT,
    tags            TEXT DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'active',
    agent_name      TEXT,
    model_used      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (app_name, user_id, session_id)
);

CREATE TABLE IF NOT EXISTS session_state (
    app_name        TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    state_key       TEXT NOT NULL,
    state_value     TEXT,
    updated_by      TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (app_name, user_id, session_id, state_key),
    FOREIGN KEY (app_name, user_id, session_id)
        REFERENCES sessions (app_name, user_id, session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_events (
    event_id        TEXT NOT NULL,
    app_name        TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    invocation_id   TEXT,
    author          TEXT NOT NULL,
    event_type      TEXT DEFAULT 'message',
    event_data      TEXT NOT NULL,
    model_used      TEXT,
    latency_ms      INTEGER,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    error_code      TEXT,
    error_message   TEXT,
    sequence_num    INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (app_name, user_id, session_id, event_id),
    FOREIGN KEY (app_name, user_id, session_id)
        REFERENCES sessions (app_name, user_id, session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS usage_tracking (
    usage_id        TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    session_id      TEXT,
    event_id        TEXT,
    app_name        TEXT NOT NULL,
    model_used      TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_microcents INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER,
    usage_date      TEXT NOT NULL DEFAULT (date('now')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tenant_quotas (
    tenant_id               TEXT PRIMARY KEY REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    monthly_token_limit     INTEGER DEFAULT 1000000,
    monthly_cost_limit_usd  REAL DEFAULT 50.00,
    monthly_session_limit   INTEGER DEFAULT 1000,
    monthly_request_limit   INTEGER DEFAULT 10000,
    current_period_start    TEXT NOT NULL DEFAULT (date('now')),
    current_tokens_used     INTEGER DEFAULT 0,
    current_cost_usd        REAL DEFAULT 0.00,
    current_sessions_count  INTEGER DEFAULT 0,
    current_requests_count  INTEGER DEFAULT 0,
    requests_per_minute     INTEGER DEFAULT 60,
    requests_per_day        INTEGER DEFAULT 10000,
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS event_feedback (
    feedback_id     TEXT PRIMARY KEY,
    app_name        TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    rating          INTEGER NOT NULL,
    feedback_type   TEXT DEFAULT 'general',
    comment         TEXT,
    tags            TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, event_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id          TEXT PRIMARY KEY,
    tenant_id       TEXT REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    user_id         TEXT,
    action          TEXT NOT NULL,
    resource_type   TEXT,
    resource_id     TEXT,
    details         TEXT DEFAULT '{}',
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS evaluation_scores (
    eval_id         TEXT PRIMARY KEY,
    app_name        TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    metric_name     TEXT NOT NULL,
    score           REAL,
    label           TEXT,
    reasoning       TEXT,
    evaluator       TEXT NOT NULL,
    eval_model      TEXT,
    eval_type       TEXT NOT NULL DEFAULT 'automated',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (event_id, metric_name, evaluator)
);

CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions (tenant_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON session_events (app_name, user_id, session_id, sequence_num);
CREATE INDEX IF NOT EXISTS idx_events_created ON session_events (created_at);
CREATE INDEX IF NOT EXISTS idx_usage_tenant ON usage_tracking (tenant_id, usage_date);
CREATE INDEX IF NOT EXISTS idx_eval_metric ON evaluation_scores (metric_name);
CREATE INDEX IF NOT EXISTS idx_eval_created ON evaluation_scores (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log (tenant_id, created_at);
"""

SEED_SQL = """
INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, display_name, status)
VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'test_app', 'Test Application', 'active');

INSERT OR IGNORE INTO tenant_users (tenant_id, user_id, role, display_name)
VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'default_user', 'owner', 'Test User');

INSERT OR IGNORE INTO tenant_quotas (tenant_id)
VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11');
"""


def get_db_path() -> str:
    return DB_PATH


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode and foreign keys."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables and seed data. Safe to call multiple times."""
    conn = get_connection()
    conn.executescript(SCHEMA_SQL)
    conn.executescript(SEED_SQL)
    conn.commit()
    conn.close()
    logger.info("SQLite DB initialized: %s (10 tables)", DB_PATH)
