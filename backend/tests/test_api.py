"""
Integration tests for the Zen backend API.

These tests exercise the HTTP endpoints through FastAPI's TestClient,
covering the acceptance criteria for authentication, memory management,
code execution, file reading, and the nudge system.

They do NOT require real API keys — external services (Gemini, mem0) are
mocked in conftest.py.
"""
import os
import json
import sqlite3
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import jwt
import bcrypt
from fastapi.testclient import TestClient


# conftest.py already mocks google.genai, mem0, and sets env vars.
from main import app, DB_PATH, JWT_SECRET, get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_db():
    """Reset the users & nudges tables before each test."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM users")
    conn.execute("DELETE FROM nudges")
    conn.commit()
    conn.close()
    yield


@pytest.fixture
def api():
    """FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture
def registered_user(api):
    """Create a user and return (token, user_dict)."""
    resp = api.post("/auth/signup", json={
        "name": "Test User",
        "email": "test@example.com",
        "password": "secure123",
    })
    assert resp.status_code == 200
    data = resp.json()
    return data["token"], data["user"]


def auth(token):
    """Build Authorization header."""
    return {"Authorization": f"Bearer {token}"}


# ===================================================================
# 1. Health endpoint
# ===================================================================

class TestHealth:
    def test_health_returns_ok(self, api):
        resp = api.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ===================================================================
# 2. Authentication — signup, login, /auth/me
# ===================================================================

class TestAuth:
    # --- signup ---
    def test_signup_success(self, api):
        resp = api.post("/auth/signup", json={
            "name": "Alice",
            "email": "alice@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["name"] == "Alice"

    def test_signup_duplicate_email(self, api):
        payload = {"name": "A", "email": "dup@example.com", "password": "password123"}
        api.post("/auth/signup", json=payload)
        resp = api.post("/auth/signup", json=payload)
        assert resp.status_code == 409
        assert "already registered" in resp.json()["detail"].lower()

    def test_signup_missing_fields(self, api):
        resp = api.post("/auth/signup", json={
            "name": "",
            "email": "a@b.com",
            "password": "password123",
        })
        assert resp.status_code == 400
        assert "required" in resp.json()["detail"].lower()

    def test_signup_short_password(self, api):
        resp = api.post("/auth/signup", json={
            "name": "Bob",
            "email": "bob@example.com",
            "password": "12345",
        })
        assert resp.status_code == 400
        assert "6 characters" in resp.json()["detail"]

    # --- login ---
    def test_login_success(self, api, registered_user):
        resp = api.post("/auth/login", json={
            "email": "test@example.com",
            "password": "secure123",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["user"]["email"] == "test@example.com"

    def test_login_wrong_password(self, api, registered_user):
        resp = api.post("/auth/login", json={
            "email": "test@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_unknown_email(self, api):
        resp = api.post("/auth/login", json={
            "email": "nobody@example.com",
            "password": "password123",
        })
        assert resp.status_code == 401

    # --- /auth/me ---
    def test_me_with_valid_token(self, api, registered_user):
        token, user = registered_user
        resp = api.get("/auth/me", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == user["email"]

    def test_me_with_invalid_token(self, api):
        resp = api.get("/auth/me", headers=auth("invalid.token.here"))
        assert resp.status_code == 401

    def test_me_with_expired_token(self, api):
        from datetime import datetime, timezone, timedelta
        payload = {
            "user_id": 1,
            "email": "x@x.com",
            "name": "X",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        resp = api.get("/auth/me", headers=auth(expired))
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_me_without_token(self, api):
        resp = api.get("/auth/me")
        assert resp.status_code in (401, 403)


# ===================================================================
# 3. Memories CRUD
# ===================================================================

class TestMemories:
    def test_get_memories_empty(self, api, registered_user):
        token, _ = registered_user
        with patch("main.memory") as mock_mem:
            mock_mem.get_all.return_value = {"results": []}
            resp = api.get("/memories", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["memories"] == []

    def test_get_memories_returns_list(self, api, registered_user):
        token, _ = registered_user
        fake_memories = [
            {"id": "m1", "memory": "User likes Python"},
            {"id": "m2", "memory": "User prefers dark mode"},
        ]
        with patch("main.memory") as mock_mem:
            mock_mem.get_all.return_value = {"results": fake_memories}
            resp = api.get("/memories", headers=auth(token))
        assert resp.status_code == 200
        assert len(resp.json()["memories"]) == 2

    def test_delete_memory_owned(self, api, registered_user):
        token, _ = registered_user
        with patch("main.memory") as mock_mem:
            mock_mem.get_all.return_value = {"results": [{"id": "m1", "memory": "test"}]}
            mock_mem.delete.return_value = None
            resp = api.delete("/memories/m1", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_memory_not_owned_returns_404(self, api, registered_user):
        """IDOR protection: cannot delete another user's memory."""
        token, _ = registered_user
        with patch("main.memory") as mock_mem:
            mock_mem.get_all.return_value = {"results": [{"id": "m1", "memory": "test"}]}
            resp = api.delete("/memories/m999", headers=auth(token))
        assert resp.status_code == 404

    def test_clear_memories(self, api, registered_user):
        token, _ = registered_user
        with patch("main.memory") as mock_mem:
            mock_mem.delete_all.return_value = None
            resp = api.delete("/memories", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "cleared"

    def test_memories_require_auth(self, api):
        resp = api.get("/memories")
        assert resp.status_code in (401, 403)


# ===================================================================
# 4. Tool functions — execute_run_code, execute_read_file
# ===================================================================

class TestToolFunctions:
    def test_run_code_hello_world(self):
        from main import execute_run_code
        result = execute_run_code("print('hello')")
        assert "hello" in result

    def test_run_code_returns_stderr(self):
        from main import execute_run_code
        result = execute_run_code("import sys; sys.stderr.write('oops')")
        assert "oops" in result

    def test_run_code_timeout(self):
        from main import execute_run_code
        import subprocess
        with patch("main.subprocess.run", side_effect=subprocess.TimeoutExpired("p", 15)):
            result = execute_run_code("while True: pass")
        assert "timed out" in result.lower()

    def test_read_file_inside_allowed_dir(self):
        from main import execute_read_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello file")
            path = f.name
        try:
            with patch("main.ALLOWED_READ_DIR", os.path.dirname(path)):
                result = execute_read_file(path)
            assert "hello file" in result
        finally:
            os.unlink(path)

    def test_read_file_outside_allowed_dir(self):
        from main import execute_read_file
        with patch("main.ALLOWED_READ_DIR", "/tmp/nonexistent_dir_xyz"):
            result = execute_read_file("/etc/hostname")
        assert "access denied" in result.lower()

    def test_read_file_too_large(self):
        from main import execute_read_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("x" * 200_000)
            path = f.name
        try:
            with patch("main.ALLOWED_READ_DIR", os.path.dirname(path)):
                result = execute_read_file(path)
            assert "too large" in result.lower()
        finally:
            os.unlink(path)

    def test_read_file_not_found(self):
        from main import execute_read_file
        d = tempfile.mkdtemp()
        with patch("main.ALLOWED_READ_DIR", d):
            result = execute_read_file(os.path.join(d, "nope.txt"))
        assert "not found" in result.lower()


# ===================================================================
# 5. Chat endpoint (mocked Gemini)
# ===================================================================

class TestChat:
    def test_chat_returns_response(self, api, registered_user):
        token, _ = registered_user
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.function_call = None
        mock_part.text = "Hello from Zen!"
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [mock_part]

        # Rating response
        mock_rating = MagicMock()
        mock_rating.text = '{"score": 2, "reason": "greeting"}'

        with patch("main.gemini_generate", side_effect=[mock_response, mock_rating]), \
             patch("main.memory") as mock_mem:
            mock_mem.search.return_value = {"results": []}
            resp = api.post("/chat", json={"message": "hi"},
                            headers=auth(token))

        assert resp.status_code == 200
        body = resp.json()
        assert body["response"] == "Hello from Zen!"
        assert "memory_score" in body
        assert "tools_used" in body

    def test_chat_handles_empty_candidates(self, api, registered_user):
        token, _ = registered_user
        mock_response = MagicMock()
        mock_response.candidates = []

        # Rating response (won't be reached but needed for mock)
        mock_rating = MagicMock()
        mock_rating.text = '{"score": 1, "reason": "n/a"}'

        with patch("main.gemini_generate", side_effect=[mock_response, mock_rating]), \
             patch("main.memory") as mock_mem:
            mock_mem.search.return_value = {"results": []}
            resp = api.post("/chat", json={"message": "hi"},
                            headers=auth(token))

        assert resp.status_code == 200
        body = resp.json()
        assert "couldn't generate" in body["response"].lower() or "try again" in body["response"].lower()

    def test_chat_requires_auth(self, api):
        resp = api.post("/chat", json={"message": "hi"})
        assert resp.status_code in (401, 403)


# ===================================================================
# 6. Memory graph
# ===================================================================

class TestMemoryGraph:
    def test_memory_graph_returns_nodes_and_edges(self, api, registered_user):
        token, _ = registered_user
        with patch("main.memory") as mock_mem:
            mock_mem.get_all.return_value = {"results": [
                {"id": "m1", "memory": "User likes Python programming", "created_at": "2026-01-01"},
                {"id": "m2", "memory": "User prefers Python over JavaScript", "created_at": "2026-01-02"},
            ]}
            resp = api.get("/memory-graph", headers=auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "edges" in body
        assert len(body["nodes"]) == 2

    def test_graph_html_page_served(self, api):
        resp = api.get("/graph")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ===================================================================
# 7. Nudge system
# ===================================================================

class TestNudge:
    def test_nudge_disabled_returns_none(self, api, registered_user):
        token, _ = registered_user
        with patch("main.NUDGE_ENABLED", False):
            resp = api.get("/nudge", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["nudge"] is None

    def test_nudge_no_memories_returns_none(self, api, registered_user):
        token, _ = registered_user
        with patch("main.memory") as mock_mem:
            mock_mem.get_all.return_value = {"results": []}
            resp = api.get("/nudge", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["nudge"] is None

    def test_dismiss_nudge(self, api, registered_user):
        token, user = registered_user
        # Insert a nudge row
        conn = get_db()
        conn.execute(
            "INSERT INTO nudges (user_email, memory_id, nudge_text) VALUES (?, ?, ?)",
            (user["email"], "m1", "How's your project going?"),
        )
        conn.commit()
        nudge_id = conn.execute("SELECT id FROM nudges WHERE user_email = ?",
                                (user["email"],)).fetchone()[0]
        conn.close()

        resp = api.post(f"/nudge/{nudge_id}/dismiss", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

        # Verify it's marked as addressed
        conn = get_db()
        row = conn.execute("SELECT addressed FROM nudges WHERE id = ?",
                           (nudge_id,)).fetchone()
        conn.close()
        assert row["addressed"] == 1


# ===================================================================
# 8. Utility functions
# ===================================================================

class TestUtilityFunctions:
    def test_extract_keywords_filters_stop_words(self):
        from main import extract_keywords
        kws = extract_keywords("the user likes Python programming")
        assert "python" in kws
        assert "programming" in kws
        assert "the" not in kws
        assert "user" not in kws  # "user" is in STOP_WORDS

    def test_extract_keywords_empty_string(self):
        from main import extract_keywords
        assert extract_keywords("") == set()

    def test_classify_memory_lesson(self):
        from main import classify_memory
        assert classify_memory("I learned that caching works well") == "lesson"
        assert classify_memory("Tools that worked: web_search") == "lesson"

    def test_classify_memory_fact(self):
        from main import classify_memory
        assert classify_memory("User works at Acme Corp") == "fact"

    def test_create_token_and_verify(self):
        from main import create_token, verify_token
        token = create_token(1, "a@b.com", "Alice")
        # Decode manually to verify structure
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        assert payload["user_id"] == 1
        assert payload["email"] == "a@b.com"
        assert payload["name"] == "Alice"
        assert "exp" in payload

    def test_gemini_generate_retries_on_429(self):
        from main import gemini_generate
        call_count = 0

        def mock_generate(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("429 RESOURCE_EXHAUSTED")
            return MagicMock(text="ok")

        with patch("main.client") as mock_client:
            mock_client.models.generate_content = mock_generate
            with patch("main.time.sleep"):
                result = gemini_generate("test")
        assert result is not None
        assert call_count == 2
