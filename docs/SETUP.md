# Setup Guide

## Prerequisites

- Python 3.11+
- PostgreSQL 15+ running locally
- Ollama with `llama3.2` model

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 2: Configure Environment

```bash
cp .env.example .env
# Edit .env with your Postgres credentials
```

## Step 3: Apply Database Schema

```bash
psql -U adk_user -d adk_sessions -f scripts/schema.sql
```

This creates 10 tables, 4 views, and 3 triggers.

## Step 4: Run the Agent

```bash
python main.py
```

Chat with the agent, then verify data in Postgres:
```sql
SELECT * FROM sessions;
SELECT * FROM session_events ORDER BY sequence_num;
SELECT * FROM usage_tracking;
SELECT * FROM audit_log;
```

## Step 5: Run Evaluation

```bash
python evaluate.py
# Or for a specific session:
python evaluate.py --session-id <id>
```

Check scores:
```sql
SELECT * FROM evaluation_scores ORDER BY created_at DESC;
```

## Step 6: Launch Dashboard

```bash
python serve.py
# Open http://localhost:8050
```

## Troubleshooting

| Issue | Fix |
|---|---|
| `psql not found` | Use full path: `"A:\Program Files\postgres\bin\psql.exe"` |
| `Phoenix PermissionError on exit` | Ignore — Windows temp file cleanup bug |
| `LiteLLM not found` | `pip install "google-adk[extensions]"` |
| `Ollama slow` | Normal for CPU — 10-30s per response |
| `Connection refused` | Check Postgres is running: `pg_isready` |
