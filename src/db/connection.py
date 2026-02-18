"""Database connection management."""

import os
import asyncpg


def get_dsn() -> str:
    """Build PostgreSQL DSN from environment variables."""
    return "postgresql://{user}:{password}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "adk_user"),
        password=os.getenv("POSTGRES_PASSWORD", "adk_password"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "adk_sessions"),
    )


async def create_pool(min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    """Create and return a connection pool."""
    return await asyncpg.create_pool(dsn=get_dsn(), min_size=min_size, max_size=max_size)
