# Zen — Self-Learning AI Agent

Zen is a conversational AI agent that remembers past interactions and learns from them. It uses Google Gemini for language generation, Mem0 for persistent memory, and provides built-in tools for web search, file reading, and Python code execution. It includes a proactive "nudge" system that surfaces relevant memories.

## Architecture

```
frontend/          React 19 + Vite 8 SPA (chat UI, auth pages)
backend/           FastAPI + SQLite (auth, agent loop, tools, nudges)
```

The frontend is a single-page React app that talks to the backend at `http://localhost:8000`. The backend runs a Gemini-powered agent loop with function-calling (web search, file read, code execution) and stores user accounts and nudges in a local SQLite database. Long-term memory is managed by the Mem0 platform API.

## Prerequisites

| Tool    | Version  | Check with          |
|---------|----------|---------------------|
| Python  | ≥ 3.10   | `python3 --version` |
| Node.js | ≥ 20     | `node --version`    |
| npm     | ≥ 10     | `npm --version`     |
| Git     | any      | `git --version`     |

## API Keys You Need

| Key              | Where to get it                                                     |
|------------------|---------------------------------------------------------------------|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey)              |
| `MEM0_API_KEY`   | [Mem0 Platform](https://app.mem0.ai/) → Settings → API Keys        |
| `JWT_SECRET`     | Generate yourself: `python3 -c "import secrets; print(secrets.token_hex(32))"` |

## Quick Start

### 1. Clone

```bash
git clone https://github.com/khyati-cl/Zen.git
cd Zen
```

### 2. Backend

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and fill in your real API keys (see table above)

# Start the API server (default: http://localhost:8000)
uvicorn main:app --reload
```

The `--reload` flag enables auto-restart on file changes during development.

### 3. Frontend

Open a **second terminal**:

```bash
cd frontend

# Install dependencies
npm ci

# Start the dev server (default: http://localhost:5173)
npm run dev
```

Open **http://localhost:5173** in your browser. Sign up for an account and start chatting.

## Environment Variables

All backend environment variables are configured in `backend/.env`. Copy from the example:

```bash
cp backend/.env.example backend/.env
```

| Variable               | Required | Default           | Description                                                |
|------------------------|----------|-------------------|------------------------------------------------------------|
| `GEMINI_API_KEY`       | **Yes**  | —                 | Google Gemini API key for language generation               |
| `MEM0_API_KEY`         | **Yes**  | —                 | Mem0 platform API key for persistent memory                |
| `JWT_SECRET`           | **Yes**  | —                 | Secret for signing JWT auth tokens (random string, ≥32 chars) |
| `ZEN_ALLOWED_READ_DIR` | No       | `~` (user home)   | Directory the `read_file` tool is allowed to access        |
| `NUDGE_ENABLED`        | No       | `true`            | Enable/disable the proactive nudge system                  |
| `NUDGE_LOOKBACK_DAYS`  | No       | `7`               | How many days back to scan for nudge-worthy memories       |

> **Security note:** `JWT_SECRET` has no default — the server refuses to start without it. Never commit your `.env` file.

## Running Tests

### Backend (pytest)

```bash
cd backend
source .venv/bin/activate

# Install pytest (not in requirements.txt)
pip install pytest

# Run all tests
python -m pytest tests/ -v
```

Expected: **26 passed**.

The test suite mocks external APIs (Gemini, Mem0) so it runs without real API keys.

### Frontend (Vitest)

```bash
cd frontend
npm test
```

Expected: **16 passed** (1 test file).

### Frontend Lint (Oxlint)

```bash
cd frontend
npm run lint
```

Expected: 0 errors (some warnings in test files are normal).

## Building for Production

### Frontend

```bash
cd frontend
npm run build
```

Output goes to `frontend/dist/`. Serve it with any static file server:

```bash
npm run preview          # Vite's built-in preview server
# or
npx serve dist           # any static server
```

### Backend

In production, drop `--reload` and bind explicitly:

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Docker (reference)

No Dockerfile is included yet. Here is a minimal setup for local containerised development:

**`backend/Dockerfile`**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`frontend/Dockerfile`**
```dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

**`docker-compose.yml`** (project root)
```yaml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file: ./backend/.env
  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend
```

```bash
docker compose up --build
```

> **Note:** When running in Docker, the frontend's hardcoded `http://localhost:8000` API URL assumes the backend is accessible on the host at that address. If you change the backend port, update `API` in `frontend/src/App.jsx` and `frontend/src/components/AuthPage.jsx`.

## Project Structure

```
Zen/
├── backend/
│   ├── main.py              # FastAPI app: auth, agent loop, tools, nudges
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Environment variable template
│   └── tests/
│       ├── conftest.py      # Test fixtures, API mocking
│       └── test_bug_fixes.py
├── frontend/
│   ├── package.json         # Node dependencies and scripts
│   ├── vite.config.js       # Vite build config
│   ├── vitest.config.js     # Test runner config
│   ├── .oxlintrc.json       # Linter config
│   ├── index.html           # Entry HTML
│   └── src/
│       ├── main.jsx         # React entry point
│       ├── App.jsx          # Root component, routing, chat state
│       ├── App.css          # Global styles
│       ├── index.css        # Base styles
│       └── components/
│           ├── AuthPage.jsx # Login / signup form
│           ├── ChatView.jsx # Chat interface
│           └── Sidebar.jsx  # Conversation sidebar
└── .gitignore
```

## Key API Endpoints

| Method | Path                    | Auth     | Description                        |
|--------|-------------------------|----------|------------------------------------|
| POST   | `/auth/signup`          | No       | Create account                     |
| POST   | `/auth/login`           | No       | Log in, receive JWT                |
| GET    | `/auth/me`              | Bearer   | Current user info                  |
| POST   | `/chat`                 | Bearer   | Send a message, get agent response |
| GET    | `/memories`             | Bearer   | List stored memories               |
| DELETE | `/memories/{id}`        | Bearer   | Delete a specific memory           |
| GET    | `/nudges`               | Bearer   | Get proactive nudges               |
| POST   | `/nudges/{id}/dismiss`  | Bearer   | Dismiss a nudge                    |
| GET    | `/graph`                | Bearer   | Memory graph visualisation (HTML)  |

## Troubleshooting

### `RuntimeError: JWT_SECRET environment variable is required`

The backend refuses to start without `JWT_SECRET`. Make sure your `backend/.env` file exists and contains a `JWT_SECRET` value:

```bash
cd backend
cp .env.example .env
# Then edit .env and set JWT_SECRET to a random string
```

### `ModuleNotFoundError: No module named 'google'` (or any import error)

You are running outside the virtual environment, or dependencies are not installed:

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
```

### `pytest: command not found` / `No module named pytest`

pytest is not in `requirements.txt` — install it separately:

```bash
pip install pytest
```

### Backend starts but frontend shows "Network Error"

The frontend expects the backend at `http://localhost:8000`. Check:

1. The backend is actually running (`uvicorn main:app` in the `backend/` directory).
2. It is on port 8000 (the default). If you changed the port, update the `API` constant in `frontend/src/App.jsx` and `frontend/src/components/AuthPage.jsx`.

### `429 / RESOURCE_EXHAUSTED` from Gemini

You have hit the Gemini API rate limit. The backend automatically retries and falls back to `gemini-2.0-flash-lite`. If it persists:

- Wait a minute and try again.
- Check your API key's quota in [Google AI Studio](https://aistudio.google.com/).

### `npm ci` fails with lockfile errors

Make sure you are using Node ≥ 20 and npm ≥ 10. Delete `node_modules` and retry:

```bash
cd frontend
rm -rf node_modules
npm ci
```

### Oxlint warnings in test files

Warnings about unused imports in test files are expected and do not affect functionality. The lint target (`npm run lint`) exits with code 0.

### SQLite `database is locked`

This can happen under heavy concurrent use because SQLite does not handle concurrent writes well. For production, consider switching to PostgreSQL. For development, this is rarely an issue with a single user.
