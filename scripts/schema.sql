-- ============================================================
-- ENTERPRISE PostgreSQL Schema for ADK Agent Platform
-- Tables: 10 | Views: 4 | Triggers: 3
--
-- Run: psql -U adk_user -d adk_sessions -f scripts/schema.sql
-- ============================================================

-- Clean slate
DROP TABLE IF EXISTS evaluation_scores CASCADE;
DROP TABLE IF EXISTS event_feedback CASCADE;
DROP TABLE IF EXISTS usage_tracking CASCADE;
DROP TABLE IF EXISTS session_events CASCADE;
DROP TABLE IF EXISTS session_state CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS tenant_quotas CASCADE;
DROP TABLE IF EXISTS tenant_users CASCADE;
DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS tenants CASCADE;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. TENANTS
-- ============================================================
CREATE TABLE tenants (
    tenant_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_name     VARCHAR(256) NOT NULL UNIQUE,
    display_name    VARCHAR(512),
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'suspended', 'trial', 'deactivated')),
    settings        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 2. TENANT USERS
-- ============================================================
CREATE TABLE tenant_users (
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    user_id         VARCHAR(256) NOT NULL,
    role            VARCHAR(50) NOT NULL DEFAULT 'user'
                    CHECK (role IN ('owner', 'admin', 'user', 'viewer')),
    display_name    VARCHAR(256),
    email           VARCHAR(256),
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'suspended', 'invited', 'deactivated')),
    preferences     JSONB DEFAULT '{}',
    last_active_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE INDEX idx_tenant_users_user ON tenant_users (user_id);

-- ============================================================
-- 3. SESSIONS
-- ============================================================
CREATE TABLE sessions (
    session_id      VARCHAR(128) NOT NULL,
    app_name        VARCHAR(256) NOT NULL,
    user_id         VARCHAR(256) NOT NULL,
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    title           VARCHAR(512),
    tags            JSONB DEFAULT '[]',
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived', 'deleted')),
    agent_name      VARCHAR(256),
    model_used      VARCHAR(128),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (app_name, user_id, session_id)
);

CREATE INDEX idx_sessions_tenant ON sessions (tenant_id);
CREATE INDEX idx_sessions_status ON sessions (status);
CREATE INDEX idx_sessions_created ON sessions (created_at DESC);

-- ============================================================
-- 4. SESSION STATE
-- ============================================================
CREATE TABLE session_state (
    app_name        VARCHAR(256) NOT NULL,
    user_id         VARCHAR(256) NOT NULL,
    session_id      VARCHAR(128) NOT NULL,
    state_key       VARCHAR(512) NOT NULL,
    state_value     JSONB,
    updated_by      VARCHAR(256),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (app_name, user_id, session_id, state_key),
    FOREIGN KEY (app_name, user_id, session_id)
        REFERENCES sessions (app_name, user_id, session_id) ON DELETE CASCADE
);

-- ============================================================
-- 5. SESSION EVENTS
-- ============================================================
CREATE TABLE session_events (
    event_id        VARCHAR(128) NOT NULL,
    app_name        VARCHAR(256) NOT NULL,
    user_id         VARCHAR(256) NOT NULL,
    session_id      VARCHAR(128) NOT NULL,
    invocation_id   VARCHAR(256),
    author          VARCHAR(256) NOT NULL,
    event_type      VARCHAR(50) DEFAULT 'message'
                    CHECK (event_type IN (
                        'message', 'tool_call', 'tool_response',
                        'state_change', 'error', 'system'
                    )),
    event_data      JSONB NOT NULL,
    model_used      VARCHAR(128),
    latency_ms      INTEGER,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    error_code      VARCHAR(50),
    error_message   TEXT,
    sequence_num    SERIAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (app_name, user_id, session_id, event_id),
    FOREIGN KEY (app_name, user_id, session_id)
        REFERENCES sessions (app_name, user_id, session_id) ON DELETE CASCADE
);

CREATE INDEX idx_events_session_order ON session_events (app_name, user_id, session_id, sequence_num);
CREATE INDEX idx_events_type ON session_events (event_type);
CREATE INDEX idx_events_created ON session_events (created_at DESC);

-- ============================================================
-- 6. USAGE TRACKING
-- ============================================================
CREATE TABLE usage_tracking (
    usage_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    user_id         VARCHAR(256) NOT NULL,
    session_id      VARCHAR(128),
    event_id        VARCHAR(128),
    app_name        VARCHAR(256) NOT NULL,
    model_used      VARCHAR(128) NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_microcents BIGINT NOT NULL DEFAULT 0,
    input_price_per_million  NUMERIC(10, 4),
    output_price_per_million NUMERIC(10, 4),
    latency_ms      INTEGER,
    usage_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_usage_tenant_date ON usage_tracking (tenant_id, usage_date);
CREATE INDEX idx_usage_user_date ON usage_tracking (tenant_id, user_id, usage_date);

-- ============================================================
-- 7. TENANT QUOTAS
-- ============================================================
CREATE TABLE tenant_quotas (
    tenant_id               UUID PRIMARY KEY REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    monthly_token_limit     BIGINT DEFAULT 1000000,
    monthly_cost_limit_usd  NUMERIC(10, 2) DEFAULT 50.00,
    monthly_session_limit   INTEGER DEFAULT 1000,
    monthly_request_limit   INTEGER DEFAULT 10000,
    current_period_start    DATE NOT NULL DEFAULT CURRENT_DATE,
    current_tokens_used     BIGINT DEFAULT 0,
    current_cost_usd        NUMERIC(10, 2) DEFAULT 0.00,
    current_sessions_count  INTEGER DEFAULT 0,
    current_requests_count  INTEGER DEFAULT 0,
    requests_per_minute     INTEGER DEFAULT 60,
    requests_per_day        INTEGER DEFAULT 10000,
    per_user_daily_tokens   BIGINT DEFAULT 100000,
    per_user_daily_requests INTEGER DEFAULT 500,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 8. EVENT FEEDBACK (User feedback)
-- ============================================================
CREATE TABLE event_feedback (
    feedback_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_name        VARCHAR(256) NOT NULL,
    user_id         VARCHAR(256) NOT NULL,
    session_id      VARCHAR(128) NOT NULL,
    event_id        VARCHAR(128) NOT NULL,
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    rating          SMALLINT NOT NULL CHECK (rating BETWEEN -1 AND 1),
    feedback_type   VARCHAR(50) DEFAULT 'general'
                    CHECK (feedback_type IN (
                        'general', 'accuracy', 'helpfulness',
                        'safety', 'speed', 'tool_usage'
                    )),
    comment         TEXT,
    tags            JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, event_id)
);

CREATE INDEX idx_feedback_session ON event_feedback (app_name, session_id);
CREATE INDEX idx_feedback_tenant ON event_feedback (tenant_id);

-- ============================================================
-- 9. AUDIT LOG
-- ============================================================
CREATE TABLE audit_log (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(tenant_id) ON DELETE SET NULL,
    user_id         VARCHAR(256),
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(256),
    details         JSONB DEFAULT '{}',
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant ON audit_log (tenant_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_log (action, created_at DESC);

-- ============================================================
-- 10. EVALUATION SCORES (Automated metrics)
-- ============================================================
CREATE TABLE evaluation_scores (
    eval_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_name        VARCHAR(256) NOT NULL,
    session_id      VARCHAR(128) NOT NULL,
    event_id        VARCHAR(128) NOT NULL,
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    metric_name     VARCHAR(100) NOT NULL,
    score           NUMERIC(5,4),
    label           VARCHAR(50),
    reasoning       TEXT,
    evaluator       VARCHAR(100) NOT NULL,
    eval_model      VARCHAR(128),
    eval_type       VARCHAR(20) NOT NULL DEFAULT 'automated'
                    CHECK (eval_type IN ('automated', 'human')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (event_id, metric_name, evaluator)
);

CREATE INDEX idx_eval_tenant ON evaluation_scores (tenant_id);
CREATE INDEX idx_eval_session ON evaluation_scores (app_name, session_id);
CREATE INDEX idx_eval_metric ON evaluation_scores (metric_name);
CREATE INDEX idx_eval_created ON evaluation_scores (created_at DESC);

-- ============================================================
-- TRIGGERS
-- ============================================================
CREATE OR REPLACE FUNCTION update_session_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE sessions SET updated_at = NOW()
    WHERE app_name = NEW.app_name AND user_id = NEW.user_id AND session_id = NEW.session_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_session_on_event
    AFTER INSERT ON session_events
    FOR EACH ROW EXECUTE FUNCTION update_session_timestamp();

CREATE TRIGGER trg_update_session_on_state
    AFTER INSERT OR UPDATE ON session_state
    FOR EACH ROW EXECUTE FUNCTION update_session_timestamp();

CREATE OR REPLACE FUNCTION update_tenant_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tenant_updated
    BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION update_tenant_timestamp();

-- ============================================================
-- VIEWS
-- ============================================================
CREATE OR REPLACE VIEW v_tenant_daily_usage AS
SELECT ut.tenant_id, t.tenant_name, ut.usage_date,
    COUNT(*) AS total_requests,
    SUM(ut.total_tokens) AS total_tokens,
    SUM(ut.cost_microcents) / 100000.0 AS total_cost_usd,
    AVG(ut.latency_ms) AS avg_latency_ms,
    COUNT(DISTINCT ut.user_id) AS active_users,
    COUNT(DISTINCT ut.session_id) AS active_sessions
FROM usage_tracking ut
JOIN tenants t ON ut.tenant_id = t.tenant_id
GROUP BY ut.tenant_id, t.tenant_name, ut.usage_date;

CREATE OR REPLACE VIEW v_model_performance AS
SELECT ut.model_used,
    COUNT(*) AS total_requests,
    AVG(ut.latency_ms) AS avg_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ut.latency_ms) AS p95_latency_ms,
    AVG(ut.total_tokens) AS avg_tokens_per_request,
    SUM(ut.cost_microcents) / 100000.0 AS total_cost_usd
FROM usage_tracking ut
WHERE ut.usage_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY ut.model_used;

CREATE OR REPLACE VIEW v_tenant_quality_weekly AS
SELECT es.tenant_id, t.tenant_name,
    DATE_TRUNC('week', es.created_at) AS week,
    es.metric_name,
    COUNT(*) AS total_evals,
    ROUND(AVG(es.score)::numeric, 4) AS avg_score,
    SUM(CASE WHEN es.label IN ('correct', 'factual', 'safe', 'faithful') THEN 1 ELSE 0 END) AS pass_count,
    SUM(CASE WHEN es.label IN ('incorrect', 'hallucinated', 'unsafe', 'unfaithful') THEN 1 ELSE 0 END) AS fail_count
FROM evaluation_scores es
JOIN tenants t ON es.tenant_id = t.tenant_id
GROUP BY es.tenant_id, t.tenant_name, week, es.metric_name;

CREATE OR REPLACE VIEW v_tenant_dashboard AS
SELECT t.tenant_id, t.tenant_name,
    COALESCE(u.total_requests, 0) AS total_requests,
    COALESCE(u.total_tokens, 0) AS total_tokens,
    COALESCE(u.total_cost_usd, 0) AS total_cost_usd,
    COALESCE(e.avg_quality_score, 0) AS avg_quality_score,
    COALESCE(e.total_evals, 0) AS total_evals,
    COALESCE(f.thumbs_up, 0) AS thumbs_up,
    COALESCE(f.thumbs_down, 0) AS thumbs_down
FROM tenants t
LEFT JOIN (
    SELECT tenant_id, COUNT(*) AS total_requests,
           SUM(total_tokens) AS total_tokens,
           SUM(cost_microcents) / 100000.0 AS total_cost_usd
    FROM usage_tracking WHERE usage_date >= CURRENT_DATE - 30
    GROUP BY tenant_id
) u ON t.tenant_id = u.tenant_id
LEFT JOIN (
    SELECT tenant_id, ROUND(AVG(score)::numeric, 4) AS avg_quality_score, COUNT(*) AS total_evals
    FROM evaluation_scores WHERE created_at >= NOW() - INTERVAL '30 days'
    GROUP BY tenant_id
) e ON t.tenant_id = e.tenant_id
LEFT JOIN (
    SELECT tenant_id,
           SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS thumbs_up,
           SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) AS thumbs_down
    FROM event_feedback WHERE created_at >= NOW() - INTERVAL '30 days'
    GROUP BY tenant_id
) f ON t.tenant_id = f.tenant_id;

-- ============================================================
-- SEED DATA
-- ============================================================
INSERT INTO tenants (tenant_id, tenant_name, display_name, status)
VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'test_app', 'Test Application', 'active')
ON CONFLICT (tenant_name) DO NOTHING;

INSERT INTO tenant_users (tenant_id, user_id, role, display_name)
VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'default_user', 'owner', 'Test User')
ON CONFLICT DO NOTHING;

INSERT INTO tenant_quotas (tenant_id)
VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11')
ON CONFLICT DO NOTHING;

SELECT '✅ Enterprise schema applied: 10 tables, 4 views, 3 triggers' AS status;
