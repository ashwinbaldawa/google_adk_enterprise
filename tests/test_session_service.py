"""Basic tests for PostgresSessionService."""

import pytest
import pytest_asyncio

# Tests require a running Postgres instance
# Run: pytest tests/ -v

pytestmark = pytest.mark.asyncio


class TestSessionService:
    """Test session CRUD operations."""

    async def test_placeholder(self):
        """Placeholder — real tests require DB connection."""
        assert True, "Test infrastructure works"
