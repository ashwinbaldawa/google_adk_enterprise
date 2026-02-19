"""Dashboard API routes — serves evaluation data to frontend."""

import json
import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api", tags=["dashboard"])

DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").lower()

# ---- SQLite helpers ----

def _sqlite_query(query: str, params: tuple = ()) -> list[dict]:
    from src.db.sqlite_connection import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---- Postgres helpers ----

_pool = None

async def _pg_query(query: str, *params) -> list[dict]:
    global _pool
    if _pool is None:
        import asyncpg
        from src.db.connection import get_dsn
        _pool = await asyncpg.create_pool(dsn=get_dsn(), min_size=1, max_size=5)
    rows = await _pool.fetch(query, *params)
    return [dict(r) for r in rows]


@router.get("/health")
async def health():
    return {"status": "ok", "db_backend": DB_BACKEND}


@router.get("/eval/summary")
async def eval_summary():
    if DB_BACKEND == "postgres":
        return await _pg_query("""
            SELECT metric_name, ROUND(AVG(score)::numeric, 4) AS avg_score,
                   COUNT(*) AS total_evals,
                   SUM(CASE WHEN score >= 0.7 THEN 1 ELSE 0 END) AS pass_count,
                   SUM(CASE WHEN score < 0.7 THEN 1 ELSE 0 END) AS fail_count
            FROM evaluation_scores GROUP BY metric_name ORDER BY metric_name
        """)
    return _sqlite_query("""
        SELECT metric_name, ROUND(AVG(score), 4) AS avg_score,
               COUNT(*) AS total_evals,
               SUM(CASE WHEN score >= 0.7 THEN 1 ELSE 0 END) AS pass_count,
               SUM(CASE WHEN score < 0.7 THEN 1 ELSE 0 END) AS fail_count
        FROM evaluation_scores GROUP BY metric_name ORDER BY metric_name
    """)


@router.get("/eval/details")
async def eval_details(limit: int = Query(default=50)):
    if DB_BACKEND == "postgres":
        rows = await _pg_query("""
            SELECT eval_id, metric_name, score, label, reasoning, eval_model, created_at,
                   event_id, session_id
            FROM evaluation_scores ORDER BY created_at DESC LIMIT $1
        """, limit)
        for r in rows:
            r["created_at"] = r["created_at"].isoformat()
            r["eval_id"] = str(r["eval_id"])
        return rows

    rows = _sqlite_query("""
        SELECT eval_id, metric_name, score, label, reasoning, eval_model, created_at,
               event_id, session_id
        FROM evaluation_scores ORDER BY created_at DESC LIMIT ?
    """, (limit,))
    return rows


@router.get("/usage/summary")
async def usage_summary():
    if DB_BACKEND == "postgres":
        return await _pg_query("""
            SELECT model_used, COUNT(*) AS total_requests,
                   COALESCE(AVG(latency_ms), 0)::int AS avg_latency_ms,
                   SUM(total_tokens) AS total_tokens
            FROM usage_tracking WHERE usage_date >= CURRENT_DATE - 30
            GROUP BY model_used
        """)
    return _sqlite_query("""
        SELECT model_used, COUNT(*) AS total_requests,
               CAST(COALESCE(AVG(latency_ms), 0) AS INTEGER) AS avg_latency_ms,
               SUM(total_tokens) AS total_tokens
        FROM usage_tracking WHERE usage_date >= date('now', '-30 days')
        GROUP BY model_used
    """)
