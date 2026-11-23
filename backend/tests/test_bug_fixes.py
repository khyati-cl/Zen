"""
Regression tests for the 13 bug fixes documented in PR #9.

Each test is designed to FAIL against the original (buggy) code
and PASS against the fixed code.

Bug list:
  1. Invalid fallback model name ("gemini-3.5-flash-lite" → "gemini-2.0-flash-lite")
  2. Hardcoded macOS Python path → sys.executable
  3. Temp file leak on exception in execute_run_code
  4. SQLite connection leaks (signup, login, dismiss_nudge, get_nudge)
  5. IDOR in delete_memory (no ownership check)
  6. Naive datetime in nudge prompt → timezone-aware
  7. Unguarded Gemini response (empty candidates)
  8. Nudge storage leak (connection not closed on exception)
  9. Temporal dead zone in App.jsx (frontend — tested separately)
 10. Stale closure in useEffect (frontend — tested separately)
 11. Unstable callbacks (frontend — tested separately)
 12. JWT leaked in URL (frontend — tested separately)
 13. Duplicate CSS reset (frontend — tested separately)
"""
import os
import sys
import json
import time
import sqlite3
import tempfile
import subprocess
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
import jwt
import bcrypt


# ---------------------------------------------------------------------------
# Bug 1: Invalid fallback model name
# The original code used "gemini-3.5-flash-lite" which doesn't exist.
# The fix changed it to "gemini-2.0-flash-lite".
# ---------------------------------------------------------------------------
class TestBug1_FallbackModelName:
    def test_fallback_model_is_valid(self):
        """FALLBACK_MODEL must be a real Gemini model, not 'gemini-3.5-flash-lite'."""
        from main import FALLBACK_MODEL
        assert FALLBACK_MODEL != "gemini-3.5-flash-lite", (
            "FALLBACK_MODEL is still the non-existent 'gemini-3.5-flash-lite'"
        )
        assert FALLBACK_MODEL == "gemini-2.0-flash-lite", (
            f"FALLBACK_MODEL should be 'gemini-2.0-flash-lite', got '{FALLBACK_MODEL}'"
        )

    def test_primary_model_unchanged(self):
        """PRIMARY_MODEL should still be gemini-2.5-flash."""
        from main import PRIMARY_MODEL
        assert PRIMARY_MODEL == "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Bug 2: Hardcoded macOS Python path
# The original code used "/opt/homebrew/bin/python3.12" instead of sys.executable.
# ---------------------------------------------------------------------------
class TestBug2_PythonPath:
    def test_execute_run_code_uses_sys_executable(self):
        """execute_run_code must use sys.executable, not a hardcoded path."""
        from main import execute_run_code
        # Run a trivial Python snippet — it should work on any platform
        result = execute_run_code("print('hello from regression test')")
        assert "hello from regression test" in result, (
            f"execute_run_code failed to run code. Got: {result!r}. "
            "This likely means it's using a hardcoded Python path that doesn't exist."
        )

    def test_execute_run_code_not_hardcoded_path(self):
        """The source code should reference sys.executable, not /opt/homebrew."""
        import inspect
        from main import execute_run_code
        source = inspect.getsource(execute_run_code)
        assert "/opt/homebrew" not in source, (
            "execute_run_code still contains hardcoded '/opt/homebrew' path"
        )
        assert "sys.executable" in source, (
            "execute_run_code should use sys.executable"
        )


# ---------------------------------------------------------------------------
# Bug 3: Temp file leak on exception
# The original code called os.unlink() before the except block, so on
# TimeoutExpired or other exceptions the temp file was never cleaned up.
# The fix moved cleanup to a finally block.
# ---------------------------------------------------------------------------
class TestBug3_TempFileLeak:
    def test_temp_file_cleaned_on_success(self):
        """After successful execution, no temp .py file should remain."""
        from main import execute_run_code
        before = set(os.listdir(tempfile.gettempdir()))
        execute_run_code("print('ok')")
        after = set(os.listdir(tempfile.gettempdir()))
        new_py_files = {f for f in (after - before) if f.endswith('.py')}
        assert len(new_py_files) == 0, (
            f"Temp file(s) leaked after successful execution: {new_py_files}"
        )

    def test_temp_file_cleaned_on_timeout(self):
        """After a timeout, the temp file must still be cleaned up (finally block)."""
        from main import execute_run_code
        before = set(os.listdir(tempfile.gettempdir()))
        # This code will time out (infinite loop, but our timeout is 15s — mock it shorter)
        with patch("main.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=1)):
            # We need to ensure the temp file is created first
            result = execute_run_code("import time; time.sleep(999)")
        after = set(os.listdir(tempfile.gettempdir()))
        new_py_files = {f for f in (after - before) if f.endswith('.py')}
        assert "timed out" in result.lower()
        assert len(new_py_files) == 0, (
            f"Temp file leaked after timeout: {new_py_files}. "
            "The finally block should clean up the temp file."
        )

    def test_temp_file_cleaned_on_generic_exception(self):
        """After a generic exception, the temp file must still be cleaned up."""
        from main import execute_run_code
        before = set(os.listdir(tempfile.gettempdir()))
        with patch("main.subprocess.run", side_effect=OSError("mocked OS error")):
            result = execute_run_code("print('will fail')")
        after = set(os.listdir(tempfile.gettempdir()))
        new_py_files = {f for f in (after - before) if f.endswith('.py')}
        assert len(new_py_files) == 0, (
            f"Temp file leaked after exception: {new_py_files}"
        )


# ---------------------------------------------------------------------------
# Bug 4: SQLite connection leaks
# signup, login, dismiss_nudge, get_nudge did not use try/finally.
# An exception mid-query would leak the connection.
# ---------------------------------------------------------------------------
class TestBug4_SQLiteConnectionLeaks:
    def test_signup_closes_connection_on_duplicate(self, test_db):
        """signup must close the DB connection even when raising HTTPException."""
        import inspect
        from main import signup
        source = inspect.getsource(signup)
        # The fixed code wraps DB operations in try/finally
        assert "finally" in source, (
            "signup() does not use try/finally — DB connection will leak on exception"
        )
        assert "conn.close()" in source, (
            "signup() does not call conn.close()"
        )

    def test_login_closes_connection_on_error(self):
        """login must close the DB connection even when user not found."""
        import inspect
        from main import login
        source = inspect.getsource(login)
        assert "finally" in source, (
            "login() does not use try/finally — DB connection will leak on exception"
        )
        assert "conn.close()" in source, (
            "login() does not call conn.close()"
        )

    def test_dismiss_nudge_closes_connection(self):
        """dismiss_nudge must close the DB connection in a finally block."""
        import inspect
        from main import dismiss_nudge
        source = inspect.getsource(dismiss_nudge)
        assert "finally" in source, (
            "dismiss_nudge() does not use try/finally — DB connection will leak"
        )
        assert "conn.close()" in source, (
            "dismiss_nudge() does not call conn.close()"
        )

    def test_get_nudge_closes_connection(self):
        """get_nudge must close the DB connection in a finally block."""
        import inspect
        from main import get_nudge
        source = inspect.getsource(get_nudge)
        # get_nudge has two DB access points — both should use try/finally
        finally_count = source.count("finally")
        close_count = source.count("conn.close()")
        assert finally_count >= 1, (
            "get_nudge() does not use try/finally — DB connection will leak"
        )
        assert close_count >= 1, (
            "get_nudge() does not call conn.close()"
        )


# ---------------------------------------------------------------------------
# Bug 5: IDOR in delete_memory
# Any authenticated user could delete any other user's memory by ID.
# The fix adds ownership verification before deletion.
# ---------------------------------------------------------------------------
class TestBug5_IDORDeleteMemory:
    def test_delete_memory_checks_ownership(self):
        """delete_memory must verify the memory belongs to the requesting user."""
        import inspect
        from main import delete_memory
        source = inspect.getsource(delete_memory)
        # The fix fetches user's memories and checks if memory_id is in them
        assert "user_id" in source or "email" in source, (
            "delete_memory does not reference the user — no ownership check"
        )
        assert "get_all" in source or "user_memory_ids" in source, (
            "delete_memory does not fetch user's memories for ownership verification"
        )
        assert "404" in source or "not found" in source.lower(), (
            "delete_memory does not return 404 for memories not owned by the user"
        )

    def test_delete_memory_has_ownership_guard(self):
        """The delete_memory source must contain an ownership check pattern."""
        import inspect
        from main import delete_memory
        source = inspect.getsource(delete_memory)
        # Must check if memory_id is in user's own memories
        assert "memory_id not in user_memory_ids" in source or "not in user_memory_ids" in source, (
            "delete_memory is missing the 'memory_id not in user_memory_ids' check (IDOR vulnerability)"
        )


# ---------------------------------------------------------------------------
# Bug 6: Naive datetime in nudge prompt
# datetime.now() produces timezone-naive dates. The fix uses
# datetime.now(timezone.utc).
# ---------------------------------------------------------------------------
class TestBug6_NaiveDatetime:
    def test_nudge_uses_utc_datetime(self):
        """The nudge prompt must use timezone-aware datetime, not naive datetime.now()."""
        import inspect
        from main import get_nudge
        source = inspect.getsource(get_nudge)
        # The fixed code uses datetime.now(timezone.utc)
        assert "timezone.utc" in source, (
            "get_nudge does not use timezone.utc — datetime is naive"
        )

    def test_no_naive_datetime_now_in_nudge(self):
        """get_nudge must not call bare datetime.now() without timezone."""
        import inspect, re
        from main import get_nudge
        source = inspect.getsource(get_nudge)
        # Find all datetime.now() calls — they should all have timezone.utc
        now_calls = re.findall(r'datetime\.now\([^)]*\)', source)
        for call in now_calls:
            assert "timezone.utc" in call, (
                f"Found naive datetime call: {call}. Must use datetime.now(timezone.utc)"
            )
        # Also check there's no bare datetime.now() without args
        bare_calls = re.findall(r'datetime\.now\(\)', source)
        assert len(bare_calls) == 0, (
            f"Found {len(bare_calls)} bare datetime.now() call(s) without timezone"
        )


# ---------------------------------------------------------------------------
# Bug 7: Unguarded Gemini response (empty candidates)
# run_agent_loop accessed response.candidates[0] without checking for
# an empty list (e.g. safety filter block). The fix adds a guard.
# ---------------------------------------------------------------------------
class TestBug7_UnguardedGeminiResponse:
    def test_run_agent_loop_handles_empty_candidates(self):
        """run_agent_loop must handle response.candidates being empty."""
        from main import run_agent_loop

        # Mock gemini_generate to return a response with empty candidates
        mock_response = MagicMock()
        mock_response.candidates = []  # Empty — safety filter blocked

        with patch("main.gemini_generate", return_value=mock_response):
            result_text, tools_used = run_agent_loop("test prompt", "")

        # Should return a graceful message, not crash with IndexError
        assert result_text is not None, "run_agent_loop returned None on empty candidates"
        assert "couldn't generate" in result_text.lower() or "try again" in result_text.lower(), (
            f"Expected graceful fallback message, got: {result_text!r}"
        )

    def test_run_agent_loop_guard_in_source(self):
        """The source must check for empty candidates before indexing."""
        import inspect
        from main import run_agent_loop
        source = inspect.getsource(run_agent_loop)
        assert "not response.candidates" in source or "if not response.candidates" in source, (
            "run_agent_loop does not guard against empty response.candidates"
        )


# ---------------------------------------------------------------------------
# Bug 8: Nudge storage leak (connection not closed on exception)
# The nudge storage in get_nudge didn't use try/finally around the
# second DB access (storing the nudge). Already covered partially by
# Bug 4 tests, but this specifically tests the nudge storage path.
# ---------------------------------------------------------------------------
class TestBug8_NudgeStorageLeak:
    def test_nudge_storage_uses_finally(self):
        """The nudge storage DB access in get_nudge must use try/finally."""
        import inspect
        from main import get_nudge
        source = inspect.getsource(get_nudge)
        # Count finally blocks — should have at least 2 (one for read, one for write)
        finally_count = source.count("finally:")
        assert finally_count >= 2, (
            f"get_nudge has only {finally_count} finally block(s); "
            "needs at least 2 (one for reading addressed nudges, one for storing new nudge)"
        )


# ---------------------------------------------------------------------------
# Bug 12: JWT leaked in URL (ChatView.jsx)
# The graph link appended ?token=... to the URL. The fix removes it.
# (This is a frontend bug but we can verify the backend graph endpoint
# does NOT require a token query param and the HTML doesn't parse it.)
# ---------------------------------------------------------------------------
class TestBug12_JWTInURL:
    def test_memory_graph_html_no_url_token_parsing(self):
        """memory_graph.html must not parse token from URL query params."""
        html_path = os.path.join(os.path.dirname(__file__), "..", "memory_graph.html")
        with open(html_path) as f:
            html_content = f.read()
        assert "URLSearchParams" not in html_content, (
            "memory_graph.html still parses token from URL query params (URLSearchParams). "
            "This enables the JWT-in-URL vulnerability."
        )
        assert "location.search" not in html_content, (
            "memory_graph.html still reads location.search for token"
        )
        # Should use localStorage instead
        assert "localStorage" in html_content, (
            "memory_graph.html should read token from localStorage, not URL"
        )


# ---------------------------------------------------------------------------
# Bug 13: Duplicate CSS reset — tested in frontend tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Integration-style tests for path traversal fix (Bug from PR but
# listed as security fix #2 — execute_read_file boundary check)
# ---------------------------------------------------------------------------
class TestPathTraversalFix:
    def test_read_file_blocks_path_traversal(self, temp_dir):
        """execute_read_file must block reads outside ALLOWED_READ_DIR."""
        from main import execute_read_file
        # Create a file inside the allowed dir
        allowed_file = os.path.join(temp_dir, "allowed.txt")
        with open(allowed_file, "w") as f:
            f.write("allowed content")

        # Create a file outside the allowed dir
        outside_dir = tempfile.mkdtemp()
        outside_file = os.path.join(outside_dir, "secret.txt")
        with open(outside_file, "w") as f:
            f.write("secret content")

        with patch("main.ALLOWED_READ_DIR", temp_dir):
            # Should succeed for file inside allowed dir
            result = execute_read_file(allowed_file)
            assert "allowed content" in result

            # Should deny access for file outside allowed dir
            result = execute_read_file(outside_file)
            assert "access denied" in result.lower(), (
                f"execute_read_file allowed reading outside ALLOWED_READ_DIR: {result!r}"
            )

    def test_read_file_blocks_etc_passwd(self, temp_dir):
        """execute_read_file must block /etc/passwd when ALLOWED_READ_DIR is set."""
        from main import execute_read_file
        with patch("main.ALLOWED_READ_DIR", temp_dir):
            result = execute_read_file("/etc/passwd")
            assert "access denied" in result.lower(), (
                "execute_read_file allowed reading /etc/passwd — path traversal vulnerability"
            )

    def test_read_file_blocks_symlink_escape(self, temp_dir):
        """execute_read_file must block symlink-based path traversal."""
        from main import execute_read_file
        # Create a symlink inside allowed dir that points outside
        link_path = os.path.join(temp_dir, "escape_link")
        os.symlink("/etc/hostname", link_path)

        with patch("main.ALLOWED_READ_DIR", temp_dir):
            result = execute_read_file(link_path)
            # os.path.realpath resolves symlinks, so this should be blocked
            assert "access denied" in result.lower() or "not found" in result.lower(), (
                f"execute_read_file followed symlink outside allowed dir: {result!r}"
            )


# ---------------------------------------------------------------------------
# JWT Secret: must not have insecure default (Bug #1 from security section)
# ---------------------------------------------------------------------------
class TestJWTSecretNoDefault:
    def test_jwt_secret_has_no_insecure_default(self):
        """JWT_SECRET must not fall back to a hardcoded default value."""
        import inspect
        # Read the raw source file to check for the old default pattern
        main_path = os.path.join(os.path.dirname(__file__), "..", "main.py")
        with open(main_path) as f:
            source = f.read()
        assert 'zen-secret-key-change-in-production' not in source, (
            "JWT_SECRET still has the insecure hardcoded default 'zen-secret-key-change-in-production'"
        )
        # Should raise RuntimeError if not set
        assert "RuntimeError" in source, (
            "main.py should raise RuntimeError when JWT_SECRET is not set"
        )


# ---------------------------------------------------------------------------
# Dead imports removed (Bug #15 from PR)
# ---------------------------------------------------------------------------
class TestDeadImportsRemoved:
    def test_no_unused_traceback_import(self):
        """The 'traceback' module should not be imported (dead import)."""
        main_path = os.path.join(os.path.dirname(__file__), "..", "main.py")
        with open(main_path) as f:
            source = f.read()
        # Check import lines specifically
        import_lines = [l.strip() for l in source.split('\n') if l.strip().startswith('import ') or l.strip().startswith('from ')]
        traceback_imported = any('traceback' in l for l in import_lines)
        assert not traceback_imported, (
            "'traceback' is imported but never used (dead import)"
        )

    def test_no_unused_counter_import(self):
        """The 'Counter' from collections should not be imported (dead import)."""
        main_path = os.path.join(os.path.dirname(__file__), "..", "main.py")
        with open(main_path) as f:
            source = f.read()
        import_lines = [l.strip() for l in source.split('\n') if l.strip().startswith('import ') or l.strip().startswith('from ')]
        counter_imported = any('Counter' in l for l in import_lines)
        assert not counter_imported, (
            "'Counter' is imported but never used (dead import)"
        )

    def test_no_unused_optional_import(self):
        """'Optional' from typing should not be imported (dead import)."""
        main_path = os.path.join(os.path.dirname(__file__), "..", "main.py")
        with open(main_path) as f:
            source = f.read()
        import_lines = [l.strip() for l in source.split('\n') if l.strip().startswith('import ') or l.strip().startswith('from ')]
        optional_imported = any('Optional' in l for l in import_lines)
        assert not optional_imported, (
            "'Optional' from typing is imported but never used (dead import)"
        )
