import os
import json
import sqlite3
import subprocess
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import re
from collections import Counter
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from google import genai
from google.genai import types
from mem0 import MemoryClient
import requests
from bs4 import BeautifulSoup
import bcrypt
import jwt

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET", "zen-secret-key-change-in-production")
NUDGE_ENABLED = os.getenv("NUDGE_ENABLED", "true").lower() in ("true", "1", "yes")
NUDGE_LOOKBACK_DAYS = int(os.getenv("NUDGE_LOOKBACK_DAYS", "7"))
client = genai.Client(api_key=GEMINI_API_KEY)

PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-3.5-flash-lite"


def gemini_generate(contents, tools=None, model=None):
    """Call Gemini with automatic retry and model fallback on rate limits."""
    target = model or PRIMARY_MODEL
    config = types.GenerateContentConfig(tools=tools) if tools else None

    for attempt in range(3):
        try:
            return client.models.generate_content(
                model=target, contents=contents, config=config,
            )
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                if attempt == 0:
                    # Try waiting briefly
                    time.sleep(3)
                elif attempt == 1 and target != FALLBACK_MODEL:
                    # Switch to fallback model
                    target = FALLBACK_MODEL
                else:
                    raise
            elif "503" in err or "UNAVAILABLE" in err:
                time.sleep(2)
                if attempt == 1 and target != FALLBACK_MODEL:
                    target = FALLBACK_MODEL
                elif attempt == 2:
                    raise
            else:
                raise


app = FastAPI(title="Zen Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize mem0 with platform API
memory = MemoryClient(api_key=MEM0_API_KEY)

# ─── SQLite Auth Database ───

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
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


init_db()

security = HTTPBearer()


def create_token(user_id: int, email: str, name: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/auth/signup")
async def signup(req: SignupRequest):
    if not req.name.strip() or not req.email.strip() or not req.password.strip():
        raise HTTPException(status_code=400, detail="All fields are required")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (req.email.lower(),)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="Email already registered")

    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
        (req.name.strip(), req.email.lower().strip(), hashed),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    token = create_token(user_id, req.email.lower(), req.name.strip())
    return {"token": token, "user": {"id": user_id, "name": req.name.strip(), "email": req.email.lower()}}


@app.post("/auth/login")
async def login(req: LoginRequest):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (req.email.lower(),)).fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not bcrypt.checkpw(req.password.encode(), user["password"].encode()):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(user["id"], user["email"], user["name"])
    return {"token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"]}}


@app.get("/auth/me")
async def get_me(payload: dict = Depends(verify_token)):
    return {"user": {"id": payload["user_id"], "name": payload["name"], "email": payload["email"]}}

# ─── Tool Definitions ───

tool_definitions = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="web_search",
            description="Search the web for current information, news, docs, or any topic. Use this when the user asks about something you don't know, need real-time data, or need to look something up.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING", description="The search query"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="read_file",
            description="Read the contents of a file from disk given its absolute path. Use this when the user wants to read, analyze, or review a file.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "file_path": types.Schema(type="STRING", description="Absolute path to the file to read"),
                },
                required=["file_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="run_code",
            description="Execute Python code and return the output. Use this for calculations, data processing, generating results, or when the user asks to run/test code.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "code": types.Schema(type="STRING", description="Python code to execute"),
                },
                required=["code"],
            ),
        ),
    ])
]

# ─── Tool Implementations ───

def execute_web_search(query: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
            timeout=10,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for r in soup.select(".result")[:5]:
            title_el = r.select_one(".result__title")
            snippet_el = r.select_one(".result__snippet")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if title or snippet:
                results.append(f"**{title}**\n{snippet}")
        return "\n\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Search error: {str(e)}"


def execute_read_file(file_path: str) -> str:
    try:
        resolved = os.path.realpath(file_path)
        if not os.path.isfile(resolved):
            return f"File not found: {file_path}"
        size = os.path.getsize(resolved)
        if size > 100_000:
            return f"File too large ({size} bytes). Max 100KB."
        with open(resolved, "r", errors="replace") as f:
            content = f.read()
        return f"File: {resolved} ({len(content)} chars)\n\n{content}"
    except Exception as e:
        return f"Read error: {str(e)}"


def execute_run_code(code: str) -> str:
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp_path = f.name
        result = subprocess.run(
            ["/opt/homebrew/bin/python3.12", tmp_path],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=tempfile.gettempdir(),
        )
        os.unlink(tmp_path)
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return output.strip() if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out (15s limit)"
    except Exception as e:
        return f"Execution error: {str(e)}"


TOOL_EXECUTORS = {
    "web_search": lambda args: execute_web_search(args["query"]),
    "read_file": lambda args: execute_read_file(args["file_path"]),
    "run_code": lambda args: execute_run_code(args["code"]),
}


SYSTEM_PROMPT = """You are Zen, a self-learning AI agent with tools. You remember past conversations and learn from interactions.

IMPORTANT: You MUST use your tools whenever possible:
- If the user asks to search, look up, or find anything → call web_search
- If the user asks to run, execute, or calculate with code → call run_code
- If the user asks to read or view a file → call read_file
- If the user asks a factual question you're unsure about → call web_search
- If the user asks for computation or data processing → call run_code

Do NOT answer questions from your own knowledge when a tool would give a better, more current, or verifiable answer. Always prefer using tools.

When you receive context from memory, use it naturally. If memory tells you a specific tool worked well for a similar task, prefer that approach.

Be helpful, concise, and thoughtful."""


class ChatRequest(BaseModel):
    message: str


def run_agent_loop(prompt: str, memory_context: str) -> tuple[str, list[dict]]:
    """Run the Gemini agent loop with function calling. Returns (response, tools_used)."""
    full_prompt = f"{SYSTEM_PROMPT}{memory_context}\n\nUser: {prompt}"

    contents = [types.Content(role="user", parts=[types.Part(text=full_prompt)])]
    tools_used = []

    # Agent loop — keep going until Gemini gives a text response
    for _ in range(5):  # max 5 tool call rounds
        response = gemini_generate(contents, tools=tool_definitions)

        # Check if the model wants to call functions
        function_calls = []
        text_parts = []
        for part in response.candidates[0].content.parts:
            if part.function_call:
                function_calls.append(part.function_call)
            if part.text:
                text_parts.append(part.text)

        if not function_calls:
            # No tool calls — we have the final response
            return "\n".join(text_parts), tools_used

        # Add model's response to conversation
        contents.append(response.candidates[0].content)

        # Execute each function call
        function_responses = []
        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            executor = TOOL_EXECUTORS.get(tool_name)
            if executor:
                result = executor(tool_args)
                tools_used.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result_preview": result[:200],
                })
            else:
                result = f"Unknown tool: {tool_name}"

            function_responses.append(
                types.Part(function_response=types.FunctionResponse(
                    name=tool_name,
                    response={"result": result},
                ))
            )

        contents.append(types.Content(role="user", parts=function_responses))

    # Fallback if loop exhausted
    return "I ran into too many tool calls. Please try a simpler question.", tools_used


@app.post("/chat")
async def chat(req: ChatRequest, payload: dict = Depends(verify_token)):
    try:
        user_id = payload["email"]

        # Search for relevant memories
        relevant_memories = memory.search(query=req.message, filters={"user_id": user_id}, top_k=5)

        memory_context = ""
        memories_list = []
        if relevant_memories:
            results = relevant_memories.get("results", relevant_memories) if isinstance(relevant_memories, dict) else relevant_memories
            memories_list = [m["memory"] for m in results if "memory" in m]
            if memories_list:
                memory_context = "\n\nRelevant memories about this user:\n" + "\n".join(
                    f"- {m}" for m in memories_list
                )

        # Run agent loop with function calling
        assistant_message, tools_used = run_agent_loop(req.message, memory_context)

        # Rate the conversation for usefulness before storing
        tools_summary = ""
        if tools_used:
            tool_names = [t["tool"] for t in tools_used]
            tools_summary = f"\nTools used: {', '.join(tool_names)}"

        rating_prompt = f"""Rate the following conversation for long-term usefulness on a scale of 1 to 5.

1 = Generic/trivial (e.g. "hi", "thanks", "ok")
2 = Low value small talk
3 = Somewhat useful context
4 = Useful personal info, preference, or insight worth remembering
5 = Highly valuable — key facts, goals, expertise, or important context

Conversation:
User: {req.message}
Assistant: {assistant_message}{tools_summary}

Respond with ONLY a single JSON object: {{"score": <number>, "reason": "<brief reason>"}}"""

        rating_response = gemini_generate(rating_prompt)

        score = 0
        reason = ""
        try:
            rating_text = rating_response.text.strip()
            if rating_text.startswith("```"):
                rating_text = rating_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            rating_data = json.loads(rating_text)
            score = int(rating_data.get("score", 0))
            reason = rating_data.get("reason", "")
        except (json.JSONDecodeError, ValueError):
            score = 3

        # Only store memories rated 4 or above
        stored = False
        if score >= 4:
            mem_content = f"User: {req.message}\nAssistant: {assistant_message}"
            if tools_used:
                tool_names = [t["tool"] for t in tools_used]
                mem_content += f"\n[Tools that worked: {', '.join(tool_names)}]"

            messages = [
                {"role": "user", "content": req.message},
                {"role": "assistant", "content": mem_content},
            ]
            memory.add(messages, user_id=user_id)
            stored = True

        return {
            "response": assistant_message,
            "memories_used": len(memories_list),
            "memory_score": score,
            "memory_stored": stored,
            "score_reason": reason,
            "tools_used": [t["tool"] for t in tools_used],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memories")
async def get_memories(payload: dict = Depends(verify_token)):
    try:
        user_id = payload["email"]
        all_memories = memory.get_all(filters={"user_id": user_id})
        results = all_memories.get("results", all_memories) if isinstance(all_memories, dict) else all_memories
        return {"memories": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, payload: dict = Depends(verify_token)):
    try:
        memory.delete(memory_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories")
async def clear_memories(payload: dict = Depends(verify_token)):
    try:
        user_id = payload["email"]
        memory.delete_all(user_id=user_id)
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Memory Graph ───

STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "and", "but", "or", "nor", "not", "so",
    "yet", "both", "either", "neither", "each", "every", "all", "any",
    "few", "more", "most", "other", "some", "such", "no", "only", "own",
    "same", "than", "too", "very", "just", "about", "up", "that", "this",
    "these", "those", "i", "me", "my", "we", "our", "you", "your", "he",
    "him", "his", "she", "her", "it", "its", "they", "them", "their",
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "user", "assistant", "also", "like", "using", "use", "based",
}


def extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#_./-]{1,}", text.lower())
    return {w for w in words if w not in STOP_WORDS}


def classify_memory(text: str) -> str:
    t = text.lower()
    lesson_signals = ["learned", "lesson", "realized", "understood", "insight",
                      "takeaway", "mistake", "works well", "should", "better to",
                      "tools that worked", "preferred", "prefers"]
    for s in lesson_signals:
        if s in t:
            return "lesson"
    return "fact"


@app.get("/memory-graph")
async def memory_graph(payload: dict = Depends(verify_token)):
    user_id = payload["email"]
    all_memories = memory.get_all(filters={"user_id": user_id})
    results = all_memories.get("results", all_memories) if isinstance(all_memories, dict) else all_memories

    nodes = []
    keyword_index: dict[str, list[int]] = {}

    for i, m in enumerate(results):
        text = m.get("memory", "")
        keywords = extract_keywords(text)
        mtype = classify_memory(text)
        nodes.append({
            "id": m.get("id", str(i)),
            "memory": text,
            "type": mtype,
            "created_at": m.get("created_at", ""),
            "updated_at": m.get("updated_at", ""),
            "keywords": list(keywords),
        })
        for kw in keywords:
            keyword_index.setdefault(kw, []).append(i)

    # Build edges from shared keywords
    edge_map: dict[tuple[int, int], list[str]] = {}
    for kw, indices in keyword_index.items():
        if len(indices) > 10:
            continue  # skip overly common words
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                pair = (indices[a], indices[b])
                edge_map.setdefault(pair, []).append(kw)

    edges = []
    for (a, b), shared in edge_map.items():
        if len(shared) >= 2:  # need at least 2 shared keywords
            edges.append({
                "source": nodes[a]["id"],
                "target": nodes[b]["id"],
                "shared": shared[:5],
                "weight": len(shared),
            })

    return {"nodes": nodes, "edges": edges}


@app.get("/graph", response_class=HTMLResponse)
async def serve_graph_page():
    html_path = os.path.join(os.path.dirname(__file__), "memory_graph.html")
    with open(html_path, "r") as f:
        return f.read()


# ─── Proactive Nudge System ───

@app.get("/nudge")
async def get_nudge(payload: dict = Depends(verify_token)):
    if not NUDGE_ENABLED:
        return {"nudge": None}

    user_id = payload["email"]

    # Get all memories
    all_memories = memory.get_all(filters={"user_id": user_id})
    results = all_memories.get("results", all_memories) if isinstance(all_memories, dict) else all_memories

    if not results:
        return {"nudge": None}

    # Filter to recent memories (last N days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=NUDGE_LOOKBACK_DAYS)
    recent = []
    for m in results:
        created = m.get("updated_at") or m.get("created_at", "")
        if created:
            try:
                mem_date = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if mem_date >= cutoff:
                    recent.append(m)
            except (ValueError, TypeError):
                recent.append(m)  # include if date unparseable
        else:
            recent.append(m)

    if not recent:
        return {"nudge": None}

    # Get already-addressed nudge memory IDs for this user
    conn = get_db()
    addressed_rows = conn.execute(
        "SELECT memory_id FROM nudges WHERE user_email = ? AND addressed = 1",
        (user_id,),
    ).fetchall()
    conn.close()
    addressed_ids = {r["memory_id"] for r in addressed_rows}

    # Filter out memories that already had their nudge addressed
    candidates = [m for m in recent if m.get("id", "") not in addressed_ids]
    if not candidates:
        return {"nudge": None}

    # Ask Gemini to identify time-sensitive or unresolved items
    memories_text = "\n".join(
        f"[ID: {m.get('id', '?')}] {m.get('memory', '')}" for m in candidates[:15]
    )

    nudge_prompt = f"""You are reviewing a user's recent memories to see if any relate to something time-sensitive or unresolved that deserves a proactive follow-up.

Today's date: {datetime.now().strftime("%A, %B %d, %Y")}

Recent memories:
{memories_text}

Rules:
- Look for: upcoming events, deadlines, unresolved problems, things the user said they'd do, interviews, exams, launches, debugging sessions with unclear outcomes, goals with pending status.
- Do NOT nudge about general facts, preferences, or casual conversation topics.
- If you find something worth following up on, respond with ONLY a JSON object:
  {{"memory_id": "<the ID>", "nudge": "<a short, warm, natural follow-up question — 1 sentence max>"}}
- If nothing is time-sensitive or unresolved, respond with:
  {{"memory_id": null, "nudge": null}}

Respond with ONLY the JSON object, no markdown or explanation."""

    try:
        response = gemini_generate(nudge_prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)

        if not data.get("nudge") or not data.get("memory_id"):
            return {"nudge": None}

        # Store the nudge so we can track if it's addressed
        conn = get_db()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO nudges (user_email, memory_id, nudge_text) VALUES (?, ?, ?)",
                (user_id, data["memory_id"], data["nudge"]),
            )
            conn.commit()
            # Get the nudge ID
            row = conn.execute(
                "SELECT id FROM nudges WHERE user_email = ? AND memory_id = ? AND addressed = 0",
                (user_id, data["memory_id"]),
            ).fetchone()
            conn.close()
        except Exception:
            conn.close()
            return {"nudge": data["nudge"], "nudge_id": None, "memory_id": data["memory_id"]}

        return {
            "nudge": data["nudge"],
            "nudge_id": row["id"] if row else None,
            "memory_id": data["memory_id"],
        }

    except (json.JSONDecodeError, Exception) as e:
        print(f"Nudge generation error: {e}")
        return {"nudge": None}


@app.post("/nudge/{nudge_id}/dismiss")
async def dismiss_nudge(nudge_id: int, payload: dict = Depends(verify_token)):
    user_id = payload["email"]
    conn = get_db()
    conn.execute(
        "UPDATE nudges SET addressed = 1 WHERE id = ? AND user_email = ?",
        (nudge_id, user_id),
    )
    conn.commit()
    conn.close()
    return {"status": "dismissed"}


@app.get("/health")
async def health():
    return {"status": "ok"}
