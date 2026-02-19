"""
Evaluation engine — orchestrates the full evaluation pipeline.

Reads events from Postgres → groups into conversations →
evaluates with 5 metrics → stores scores in evaluation_scores table.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import asyncpg

from .judge import OllamaJudge
from .metrics import (
    evaluate_tool_accuracy,
    evaluate_answer_correctness,
    evaluate_safety,
    evaluate_routing_accuracy,
    evaluate_faithfulness,
)

logger = logging.getLogger(__name__)

AVAILABLE_TOOLS = ["get_current_time", "remember_info", "recall_info", "calculate"]


def extract_conversations(events: list[dict]) -> list[dict]:
    """Group raw events into conversation units for evaluation."""
    conversations = []
    current = None

    for event in events:
        author = event.get("author", "")
        event_data = event.get("event_data", {})
        content = event_data.get("content", {})
        parts = content.get("parts", []) if content else []

        if author == "user":
            if current and current.get("agent_response"):
                conversations.append(current)
            current = {
                "event_id": event.get("event_id", ""),
                "user_query": "",
                "tool_calls": [],
                "tool_outputs": [],
                "agent_response": "",
                "agent_event_id": "",
            }
            for part in parts:
                if "text" in part:
                    current["user_query"] = part["text"]

        elif current is not None:
            for part in parts:
                if "function_call" in part:
                    fc = part["function_call"]
                    current["tool_calls"].append({
                        "name": fc.get("name", ""),
                        "args": fc.get("args", {}),
                    })
                if "function_response" in part:
                    fr = part["function_response"]
                    current["tool_outputs"].append(json.dumps(fr.get("response", {})))
            if author != "user":
                for part in parts:
                    if "text" in part and part["text"]:
                        current["agent_response"] = part["text"]
                        current["agent_event_id"] = event.get("event_id", "")

    if current and current.get("agent_response"):
        conversations.append(current)

    return conversations


async def fetch_events(
    pool: asyncpg.Pool, app_name: str,
    session_id: Optional[str] = None, limit: int = 50,
) -> list[dict]:
    """Fetch events from Postgres."""
    if session_id:
        rows = await pool.fetch(
            """SELECT event_id, author, event_type, event_data, session_id
               FROM session_events WHERE app_name=$1 AND session_id=$2
               ORDER BY sequence_num ASC""",
            app_name, session_id,
        )
    else:
        rows = await pool.fetch(
            """SELECT event_id, author, event_type, event_data, session_id
               FROM session_events WHERE app_name=$1
               ORDER BY sequence_num DESC LIMIT $2""",
            app_name, limit,
        )
        rows = list(reversed(rows))

    events = []
    for r in rows:
        d = r["event_data"]
        if isinstance(d, str):
            d = json.loads(d)
        events.append({
            "event_id": r["event_id"], "author": r["author"],
            "event_type": r["event_type"], "event_data": d,
            "session_id": r["session_id"],
        })
    return events


def fetch_events_sqlite(
    app_name: str, session_id: Optional[str] = None, limit: int = 50,
) -> list[dict]:
    """Fetch events from SQLite."""
    from src.db.sqlite_connection import get_connection
    conn = get_connection()
    try:
        if session_id:
            rows = conn.execute(
                "SELECT event_id, author, event_type, event_data, session_id FROM session_events WHERE app_name=? AND session_id=? ORDER BY sequence_num ASC",
                (app_name, session_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT event_id, author, event_type, event_data, session_id FROM session_events WHERE app_name=? ORDER BY sequence_num DESC LIMIT ?",
                (app_name, limit),
            ).fetchall()
            rows = list(reversed(rows))
    finally:
        conn.close()

    events = []
    for r in rows:
        d = r["event_data"]
        if isinstance(d, str):
            d = json.loads(d)
        events.append({
            "event_id": r["event_id"], "author": r["author"],
            "event_type": r["event_type"], "event_data": d,
            "session_id": r["session_id"],
        })
    return events


async def store_score(
    pool, app_name, session_id, event_id, tenant_id,
    metric_name, score, label, reasoning, evaluator, eval_model,
):
    """Store evaluation score in Postgres."""
    await pool.execute(
        """INSERT INTO evaluation_scores
           (app_name, session_id, event_id, tenant_id,
            metric_name, score, label, reasoning, evaluator, eval_model, eval_type)
           VALUES ($1,$2,$3,$4::uuid,$5,$6,$7,$8,$9,$10,'automated')
           ON CONFLICT (event_id, metric_name, evaluator)
           DO UPDATE SET score=$6, label=$7, reasoning=$8""",
        app_name, session_id, event_id, tenant_id,
        metric_name, score, label, reasoning, evaluator, eval_model,
    )


def store_score_sqlite(
    app_name, session_id, event_id, tenant_id,
    metric_name, score, label, reasoning, evaluator, eval_model,
):
    """Store evaluation score in SQLite."""
    import uuid as _uuid
    from src.db.sqlite_connection import get_connection
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO evaluation_scores
               (eval_id, app_name, session_id, event_id, tenant_id,
                metric_name, score, label, reasoning, evaluator, eval_model, eval_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'automated')
               ON CONFLICT (event_id, metric_name, evaluator)
               DO UPDATE SET score=?, label=?, reasoning=?""",
            (str(_uuid.uuid4()), app_name, session_id, event_id, tenant_id,
             metric_name, score, label, reasoning, evaluator, eval_model,
             score, label, reasoning),
        )
        conn.commit()
    finally:
        conn.close()


async def run_evaluation(session_id: Optional[str] = None, limit: int = 50):
    """Run the full evaluation pipeline."""
    app_name = os.getenv("APP_NAME", "my_adk_agent")
    tenant_id = os.getenv("TENANT_ID", "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
    agent_name = os.getenv("AGENT_NAME", "assistant")
    backend = os.getenv("DB_BACKEND", "sqlite").lower()

    judge = OllamaJudge()

    if backend == "postgres":
        from src.db.connection import get_dsn
        pool = await asyncpg.create_pool(dsn=get_dsn(), min_size=1, max_size=3)
        db_type = "postgres"
    else:
        pool = None
        db_type = "sqlite"

    print(f"\n{'='*60}")
    print(f"🔍 Agent Evaluation Pipeline")
    print(f"   Judge: {judge.model_name} (via Ollama)")
    print(f"   App: {app_name}")
    if session_id:
        print(f"   Session: {session_id}")
    print(f"{'='*60}\n")

    # Fetch & group
    print("📥 Fetching events...")
    if db_type == "postgres":
        events = await fetch_events(pool, app_name, session_id, limit)
    else:
        events = fetch_events_sqlite(app_name, session_id, limit)
    print(f"   Found {len(events)} events")

    if not events:
        print("❌ No events found. Chat with the agent first!")
        await pool.close()
        return

    conversations = extract_conversations(events)
    print(f"   Grouped into {len(conversations)} conversations\n")

    if not conversations:
        print("❌ No complete conversations found.")
        await pool.close()
        return

    # Evaluate
    totals = {m: [] for m in ["tool_accuracy", "answer_correctness", "safety", "routing_accuracy", "faithfulness"]}

    for i, conv in enumerate(conversations):
        query = conv["user_query"]
        response = conv["agent_response"]
        tool_output = " | ".join(conv["tool_outputs"]) if conv["tool_outputs"] else ""
        event_id = conv["agent_event_id"] or conv["event_id"]
        sid = events[0]["session_id"]

        print(f"{'─'*50}")
        print(f"📝 Conversation {i+1}/{len(conversations)}")
        print(f"   User:  {query[:80]}")
        print(f"   Agent: {response[:80]}")
        print()

        evals = [
            ("tool_accuracy", evaluate_tool_accuracy(judge, query, conv["tool_calls"], response, AVAILABLE_TOOLS)),
            ("answer_correctness", evaluate_answer_correctness(judge, query, response, tool_output)),
            ("safety", evaluate_safety(judge, query, response)),
            ("routing_accuracy", evaluate_routing_accuracy(judge, query, conv["tool_calls"], agent_name, AVAILABLE_TOOLS)),
            ("faithfulness", evaluate_faithfulness(judge, response, tool_output)),
        ]

        for metric_name, (label, score, reason) in evals:
            totals[metric_name].append(score)
            if db_type == "postgres":
                await store_score(
                    pool, app_name, sid, event_id, tenant_id,
                    metric_name, score, label, reason,
                    "ollama_judge", judge.model_name,
                )
            else:
                store_score_sqlite(
                    app_name, sid, event_id, tenant_id,
                    metric_name, score, label, reason,
                    "ollama_judge", judge.model_name,
                )
            emoji = "✅" if score >= 0.7 else "⚠️" if score >= 0.4 else "❌"
            print(f"   {emoji} {metric_name:25s} | score={score:.2f} | {label}")
        print()

    # Summary
    print(f"\n{'='*60}")
    print(f"📊 EVALUATION SUMMARY")
    print(f"{'='*60}")
    print(f"   Conversations: {len(conversations)} | Judge: {judge.model_name}\n")

    for metric, scores in totals.items():
        if scores:
            avg = sum(scores) / len(scores)
            emoji = "✅" if avg >= 0.7 else "⚠️" if avg >= 0.4 else "❌"
            print(f"   {emoji} {metric:25s} | avg={avg:.2f} | n={len(scores)}")

    print(f"\n   Scores stored in: evaluation_scores table")
    print(f"{'='*60}\n")

    if pool:
        await pool.close()
