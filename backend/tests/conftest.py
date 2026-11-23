"""
Shared fixtures for backend regression tests.
These tests verify the 13 bug fixes from PR #9.

Since the app depends on google-genai and mem0ai which require API keys,
we mock those at import time so we can test the fixed functions in isolation.
"""
import os
import sys
import sqlite3
import tempfile
from unittest.mock import MagicMock

import pytest

# Set required env vars BEFORE importing main (which reads them at module level)
os.environ["JWT_SECRET"] = "test-secret-for-regression-tests"
os.environ["GEMINI_API_KEY"] = "fake-key-for-tests"
os.environ["MEM0_API_KEY"] = "fake-key-for-tests"
os.environ["NUDGE_ENABLED"] = "false"

# Mock external dependencies that require real API keys / network
# before main.py is imported
_mock_genai = MagicMock()
_mock_types = MagicMock()
_mock_mem0 = MagicMock()

sys.modules["google"] = MagicMock()
sys.modules["google.genai"] = _mock_genai
sys.modules["google.genai.types"] = _mock_types
sys.modules["mem0"] = _mock_mem0

# Provide the types that main.py references
_mock_types.Tool = MagicMock
_mock_types.FunctionDeclaration = MagicMock
_mock_types.Schema = MagicMock
_mock_types.Content = MagicMock
_mock_types.Part = MagicMock
_mock_types.FunctionResponse = MagicMock
_mock_types.GenerateContentConfig = MagicMock

# Make genai.Client return a mock
_mock_genai.Client = MagicMock


@pytest.fixture
def temp_dir():
    """Provide a fresh temp directory for file-system tests."""
    d = tempfile.mkdtemp()
    yield d


@pytest.fixture
def test_db():
    """Provide a fresh SQLite database for auth tests."""
    db_path = os.path.join(tempfile.mkdtemp(), "test_users.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nudges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            nudge_text TEXT NOT NULL,
            addressed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_email, memory_id)
        )
    """)
    conn.commit()
    conn.close()
    yield db_path
