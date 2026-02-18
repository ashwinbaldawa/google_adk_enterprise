"""Dashboard API routes — serves evaluation data to frontend."""

import json
import os
from typing import Optional

import asyncpg
from fastapi import APIRouter, Query

from src.db.connection import get_dsn

router = APIRouter(prefix="/api", tags=["dashboard"])

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=get_dsn(), min_size=1, max_size=5)
    return _pool


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/eval/summary")
async def eval_summary():
    """Overall evaluation summary — avg scores per metric."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT metric_name,
               ROUND(AVG(score)::numeric, 4) AS avg_score,
               COUNT(*) AS total_evals,
               SUM(CASE WHEN score >= 0.7 THEN 1 ELSE 0 END) AS pass_count,
               SUM(CASE WHEN score < 0.7 THEN 1 ELSE 0 END) AS fail_count
        FROM evaluation_scores
        GROUP BY metric_name
        ORDER BY metric_name
    """)
    return [dict(r) for r in rows]


@router.get("/eval/history")
async def eval_history(metric: str = Query(default=None), days: int = Query(default=30)):
    """Evaluation scores over time."""
    pool = await get_pool()

    if metric:
        rows = await pool.fetch("""
            SELECT DATE(created_at) AS eval_date,
                   ROUND(AVG(score)::numeric, 4) AS avg_score,
                   COUNT(*) AS count
            FROM evaluation_scores
            WHERE metric_name = $1
              AND created_at >= NOW() - MAKE_INTERVAL(days => $2)
            GROUP BY eval_date
            ORDER BY eval_date
        """, metric, days)
    else:
        rows = await pool.fetch("""
            SELECT DATE(created_at) AS eval_date,
                   metric_name,
                   ROUND(AVG(score)::numeric, 4) AS avg_score,
                   COUNT(*) AS count
            FROM evaluation_scores
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => $1)
            GROUP BY eval_date, metric_name
            ORDER BY eval_date, metric_name
        """, days)

    return [dict(r) for r in rows]


@router.get("/eval/details")
async def eval_details(limit: int = Query(default=50)):
    """Individual evaluation scores with event details."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT es.eval_id, es.metric_name, es.score, es.label,
               es.reasoning, es.eval_model, es.created_at,
               es.event_id, es.session_id
        FROM evaluation_scores es
        ORDER BY es.created_at DESC
        LIMIT $1
    """, limit)
    results = []
    for r in rows:
        d = dict(r)
        d["created_at"] = d["created_at"].isoformat()
        d["eval_id"] = str(d["eval_id"])
        results.append(d)
    return results


@router.get("/eval/conversations")
async def eval_conversations(session_id: str = Query(default=None), limit: int = Query(default=20)):
    """Get conversation-level evaluation with user query and agent response."""
    pool = await get_pool()

    query = """
        SELECT es.event_id, es.session_id, es.metric_name, es.score, es.label, es.reasoning,
               se.event_data, se.author
        FROM evaluation_scores es
        JOIN session_events se
            ON es.app_name = se.app_name AND es.session_id = se.session_id AND es.event_id = se.event_id
    """
    params = []

    if session_id:
        query += " WHERE es.session_id = $1"
        params.append(session_id)

    query += " ORDER BY se.sequence_num DESC, es.metric_name"
    if not session_id:
        query += f" LIMIT {limit * 5}"

    rows = await pool.fetch(query, *params)

    results = []
    for r in rows:
        d = dict(r)
        ed = d.pop("event_data")
        if isinstance(ed, str):
            ed = json.loads(ed)
        # Extract response text
        text = ""
        if ed.get("content", {}).get("parts"):
            for part in ed["content"]["parts"]:
                if "text" in part:
                    text = part["text"]
                    break
        d["response_text"] = text[:200]
        results.append(d)

    return results


@router.get("/usage/summary")
async def usage_summary():
    """Usage tracking summary."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT model_used,
               COUNT(*) AS total_requests,
               COALESCE(AVG(latency_ms), 0)::int AS avg_latency_ms,
               SUM(total_tokens) AS total_tokens
        FROM usage_tracking
        WHERE usage_date >= CURRENT_DATE - 30
        GROUP BY model_used
    """)
    return [dict(r) for r in rows]


@router.get("/tenant/dashboard")
async def tenant_dashboard():
    """Combined tenant dashboard view."""
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM v_tenant_dashboard")
    results = []
    for r in rows:
        d = dict(r)
        d["tenant_id"] = str(d["tenant_id"])
        for k, v in d.items():
            if hasattr(v, "__float__"):
                d[k] = float(v)
        results.append(d)
    return results
