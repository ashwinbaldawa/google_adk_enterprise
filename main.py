"""
Entry point: Run ADK Agent with Enterprise Postgres + Phoenix.

Usage:
    python main.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Setup observability BEFORE importing ADK
from src.observability import setup_observability

has_observability = setup_observability()

from google.adk import Runner
from google.genai import types

from src.agent import root_agent
from src.db import PostgresSessionService, SQLiteSessionService


async def create_session_service(tenant_id, agent_name, model_used):
    """Create session service based on DB_BACKEND env var."""
    backend = os.getenv("DB_BACKEND", "sqlite").lower()

    if backend == "postgres":
        print("\n🔌 Connecting to PostgreSQL...")
        return await PostgresSessionService.create(
            tenant_id=tenant_id, agent_name=agent_name, model_used=model_used,
        )
    else:
        db_path = os.getenv("SQLITE_DB_PATH", "adk_enterprise.db")
        print(f"\n🔌 Using SQLite: {db_path}")
        return await SQLiteSessionService.create(
            tenant_id=tenant_id, agent_name=agent_name, model_used=model_used,
        )


async def run_interactive():
    app_name = os.getenv("APP_NAME", "my_adk_agent")
    tenant_id = os.getenv("TENANT_ID", "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
    agent_name = os.getenv("AGENT_NAME", "assistant")
    model_used = os.getenv("MODEL_USED", "ollama/llama3.2")

    try:
        session_service = await create_session_service(tenant_id, agent_name, model_used)
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        sys.exit(1)

    print(f"✅ Connected | tenant={tenant_id[:8]}...")

    runner = Runner(agent=root_agent, app_name=app_name, session_service=session_service)

    user_id = input("\n👤 Enter user ID (or Enter for 'default_user'): ").strip() or "default_user"

    existing = await session_service.list_sessions(app_name=app_name, user_id=user_id)
    session = None

    if existing.sessions:
        print(f"\n📋 Found {len(existing.sessions)} session(s):")
        for i, s in enumerate(existing.sessions):
            print(f"   [{i+1}] {s.id[:16]}...")
        choice = input("\nResume # or 'n' for new: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(existing.sessions):
            chosen = existing.sessions[int(choice) - 1]
            session = await session_service.get_session(
                app_name=app_name, user_id=user_id, session_id=chosen.id,
            )
            print(f"📂 Resumed: {session.id[:16]}... ({len(session.events)} events)")

    if session is None:
        session = await session_service.create_session(app_name=app_name, user_id=user_id)
        print(f"🆕 New session: {session.id[:16]}...")

    print(f"\n{'='*60}")
    print(f"💬 Chat (type 'quit' to exit)")
    print(f"   /state | /events | /info{' | /traces' if has_observability else ''}")
    print(f"{'='*60}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            break

        if user_input == "/state":
            fresh = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session.id)
            print(f"📊 State: {fresh.state}")
            continue
        if user_input == "/events":
            fresh = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session.id)
            print(f"📜 Events: {len(fresh.events)}")
            continue
        if user_input == "/info":
            print(f"   Session: {session.id}\n   Tenant: {tenant_id[:8]}...\n   Model: {model_used}")
            continue
        if user_input == "/traces":
            print("🔭 http://localhost:6006")
            continue

        content = types.Content(role="user", parts=[types.Part(text=user_input)])
        try:
            print("Agent: ", end="", flush=True)
            async for event in runner.run_async(
                user_id=user_id, session_id=session.id, new_message=content,
            ):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        print(event.content.parts[0].text)
                    else:
                        print("[no response]")
            print()
        except Exception as e:
            print(f"\n❌ Error: {e}")

    await session_service.close()
    print("\n👋 Done.")


if __name__ == "__main__":
    asyncio.run(run_interactive())
