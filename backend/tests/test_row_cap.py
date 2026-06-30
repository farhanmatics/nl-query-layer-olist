"""Offline unit tests for the global row cap enforcement.

Pure Python — no DB, no LLM. These pin that execute_query raises RowCapExceeded
when a query returns more rows than the configured cap. Run:

    cd backend && ../venv/bin/python -m pytest tests/test_row_cap.py -v
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import RowCapExceeded, execute_query  # noqa: E402
from config import settings  # noqa: E402


def test_row_cap_exception_has_correct_fields():
    exc = RowCapExceeded(500, 200)
    assert exc.row_count == 500
    assert exc.cap == 200
    assert "500 rows" in str(exc)
    assert "200-row cap" in str(exc)


def test_default_cap_is_200():
    assert settings.max_result_rows == 200


async def test_execute_query_raises_on_over_cap():
    """execute_query must raise RowCapExceeded when rows exceed the cap."""
    fake_rows = [{"id": i} for i in range(250)]

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=fake_rows)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("db.get_pool", new=AsyncMock(return_value=mock_pool)):
        try:
            await execute_query("SELECT * FROM big_table")
            assert False, "Expected RowCapExceeded"
        except RowCapExceeded as e:
            assert e.row_count == 250
            assert e.cap == settings.max_result_rows


async def test_execute_query_passes_under_cap():
    """execute_query must NOT raise when rows are under the cap."""
    fake_rows = [{"id": i} for i in range(50)]

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=fake_rows)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("db.get_pool", new=AsyncMock(return_value=mock_pool)):
        result = await execute_query("SELECT * FROM small_table")
        assert len(result) == 50


async def test_execute_query_passes_at_exact_cap():
    """execute_query must NOT raise when rows equal the cap exactly."""
    fake_rows = [{"id": i} for i in range(settings.max_result_rows)]

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=fake_rows)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("db.get_pool", new=AsyncMock(return_value=mock_pool)):
        result = await execute_query("SELECT * FROM exact_table")
        assert len(result) == settings.max_result_rows
