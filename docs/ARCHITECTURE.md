# Architecture

## System Overview

```
Client (CLI / API)
    │
    ▼
ADK Agent Runtime (Google ADK + LlmAgent)
    │
    ├──► PostgreSQL (Enterprise Session Service)
    │    ├── sessions, events, state (ADK data)
    │    ├── usage_tracking, quotas (business data)
    │    ├── event_feedback (user feedback)
    │    ├── evaluation_scores (automated quality)
    │    └── audit_log (compliance)
    │
    └──► OpenTelemetry (Traces)
         └── Phoenix (dev) / Dynatrace (prod) / Datadog (prod)
```

## Data Flow

### Request Flow
1. User sends message via CLI or API
2. ADK Runner passes to LlmAgent
3. Agent calls LLM (Ollama/Gemini) via LiteLLM
4. If tool needed: agent calls tool, gets response, calls LLM again
5. Final response returned to user
6. Event persisted to Postgres (session_events)
7. Usage tracked (usage_tracking)
8. Trace sent to Phoenix via OpenTelemetry

### Evaluation Flow
1. `evaluate.py` reads events from Postgres
2. Groups events into conversations
3. Sends each conversation through 5 metric evaluators
4. Each evaluator prompts the judge LLM
5. Scores stored in evaluation_scores table
6. Dashboard reads scores via FastAPI endpoints

## Multi-Tenancy

Every operation is scoped to a `tenant_id`:
- Sessions are created with tenant_id
- Queries always filter by tenant_id
- Usage is tracked per tenant
- Evaluations are linked to tenant

## Key Design Decisions

| Decision | Rationale |
|---|---|
| asyncpg over SQLAlchemy | Direct control, better async performance |
| Normalized session_state | Fast individual key updates |
| Separate event_feedback & evaluation_scores | User feedback ≠ automated metrics |
| OpenTelemetry standard | Vendor-agnostic, swap backends freely |
| LLM-as-Judge pattern | Flexible, works with any LLM |
