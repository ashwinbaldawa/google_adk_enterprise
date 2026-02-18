# ADK Enterprise Agent Platform

A production-grade multi-tenant agent platform built on **Google ADK** with custom PostgreSQL session management, OpenTelemetry observability, and automated LLM evaluation.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Client / CLI / API                        │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│                  Google ADK Agent Runtime                      │
│              (LlmAgent + Tools + Runner)                      │
└──────┬──────────────────────┬────────────────────────────────┘
       │                      │
       ▼                      ▼
┌──────────────┐    ┌─────────────────┐
│  PostgreSQL   │    │  OpenTelemetry   │
│  Enterprise   │    │  (OTLP Export)   │
│              │    │                  │
│  10 Tables:  │    │  → Phoenix (dev) │
│  - sessions  │    │  → Dynatrace     │
│  - events    │    │  → Datadog       │
│  - usage     │    │                  │
│  - evals     │    └─────────────────┘
│  - audit     │
│  - feedback  │
└──────────────┘
       │
       ▼
┌──────────────────┐    ┌──────────────────┐
│  Evaluation       │    │  Dashboard        │
│  Pipeline         │    │  (FastAPI +       │
│  (5 metrics,      │    │   HTML/JS)        │
│   LLM-as-Judge)   │    │                   │
└──────────────────┘    └──────────────────┘
```

## Features

- **Multi-Tenant Isolation** — Each consuming application gets its own tenant context
- **Enterprise PostgreSQL Schema** — 10 tables: sessions, events, state, usage tracking, quotas, feedback, audit, evaluations
- **OpenTelemetry Instrumentation** — Traces to Phoenix (local), Dynatrace, Datadog
- **Automated Evaluation** — 5 metrics with LLM-as-Judge (Ollama local / Vertex AI / Ragas)
- **Evaluation Dashboard** — Real-time quality monitoring UI
- **ADK Compatible** — Standard `BaseSessionService` interface

## Project Structure

```
adk-enterprise-agent/
├── src/
│   ├── agent/                  # ADK Agent definition
│   │   ├── __init__.py
│   │   ├── agent.py            # Agent + tools
│   │   └── tools.py            # Tool functions
│   ├── db/                     # Database layer
│   │   ├── __init__.py
│   │   ├── session_service.py  # Enterprise PostgresSessionService
│   │   └── connection.py       # Connection pool management
│   ├── evaluation/             # Evaluation pipeline
│   │   ├── __init__.py
│   │   ├── engine.py           # Evaluation orchestrator
│   │   ├── metrics.py          # 5 metric implementations
│   │   └── judge.py            # LLM judge (Ollama/Vertex AI)
│   ├── observability/          # OpenTelemetry setup
│   │   ├── __init__.py
│   │   └── setup.py            # Phoenix/Dynatrace/Datadog config
│   └── api/                    # FastAPI endpoints
│       ├── __init__.py
│       ├── app.py              # FastAPI app
│       └── routes.py           # Dashboard API routes
├── dashboard/                  # Evaluation dashboard UI
│   └── index.html              # Single-file dashboard
├── scripts/                    # Database & utility scripts
│   ├── schema.sql              # Full enterprise schema (10 tables)
│   └── seed.sql                # Test seed data
├── tests/                      # Test suite
│   └── test_session_service.py
├── docs/                       # Documentation
│   ├── SETUP.md                # Step-by-step setup guide
│   ├── ARCHITECTURE.md         # Architecture deep dive
│   └── EVALUATION.md           # Evaluation metrics guide
├── .env.example                # Environment template
├── .gitignore
├── requirements.txt
├── main.py                     # CLI runner entry point
├── evaluate.py                 # Evaluation runner entry point
└── serve.py                    # Dashboard server entry point
```

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Ollama with llama3.2 (or Gemini API key)

### Setup

```bash
# 1. Clone
git clone https://github.com/your-org/adk-enterprise-agent.git
cd adk-enterprise-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env with your Postgres credentials

# 4. Apply database schema
psql -U adk_user -d adk_sessions -f scripts/schema.sql

# 5. Run the agent
python main.py

# 6. Run evaluation
python evaluate.py

# 7. Launch dashboard
python serve.py
# Open http://localhost:8050
```

## Evaluation Metrics

| Metric | What It Measures | Judge Type |
|---|---|---|
| Tool Accuracy | Correct tool called with right params | LLM-as-Judge |
| Answer Correctness | Response is factually correct and complete | LLM-as-Judge |
| Safety | No harmful content, PHI leaks, medical advice | LLM-as-Judge |
| Routing Accuracy | Query handled by correct agent/capability | LLM-as-Judge |
| Faithfulness | Response grounded in tool output only | LLM-as-Judge |

## Tech Stack

- **Agent Framework**: Google ADK
- **Database**: PostgreSQL 15+ (asyncpg)
- **Observability**: OpenTelemetry + Arize Phoenix
- **Evaluation**: Custom LLM-as-Judge (Ollama / Vertex AI Eval SDK)
- **API**: FastAPI + Uvicorn
- **Dashboard**: Vanilla HTML/JS + Chart.js

## License

MIT
