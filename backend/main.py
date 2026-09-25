import os
import json
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from google import genai
from mem0 import MemoryClient

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

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

SYSTEM_PROMPT = """You are Zen, a self-learning AI assistant. You have the ability to remember past conversations and learn from interactions.

When you receive context from memory, use it naturally to provide more personalized and relevant responses. Reference what you remember when appropriate, but don't be robotic about it.

You are helpful, concise, and thoughtful. You adapt your communication style based on what you learn about the user."""


class ChatRequest(BaseModel):
    message: str
    user_id: str = "default_user"


class MemoryRequest(BaseModel):
    user_id: str = "default_user"


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        # Search for relevant memories
        relevant_memories = memory.search(query=req.message, filters={"user_id": req.user_id}, top_k=5)

        memory_context = ""
        if relevant_memories:
            results = relevant_memories.get("results", relevant_memories) if isinstance(relevant_memories, dict) else relevant_memories
            memories_list = [m["memory"] for m in results if "memory" in m]
            memory_context = "\n\nRelevant memories about this user:\n" + "\n".join(
                f"- {m}" for m in memories_list
            )

        prompt = f"{SYSTEM_PROMPT}{memory_context}\n\nUser: {req.message}"

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        assistant_message = response.text

        # Rate the conversation for usefulness before storing
        rating_prompt = f"""Rate the following conversation for long-term usefulness on a scale of 1 to 5.

1 = Generic/trivial (e.g. "hi", "thanks", "ok")
2 = Low value small talk
3 = Somewhat useful context
4 = Useful personal info, preference, or insight worth remembering
5 = Highly valuable — key facts, goals, expertise, or important context

Conversation:
User: {req.message}
Assistant: {assistant_message}

Respond with ONLY a single JSON object: {{"score": <number>, "reason": "<brief reason>"}}"""

        rating_response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=rating_prompt,
        )

        score = 0
        reason = ""
        try:
            rating_text = rating_response.text.strip()
            # Strip markdown code fences if present
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
            messages = [
                {"role": "user", "content": req.message},
                {"role": "assistant", "content": assistant_message},
            ]
            memory.add(messages, user_id=req.user_id)
            stored = True

        return {
            "response": assistant_message,
            "memories_used": len(memories_list) if memory_context else 0,
            "memory_score": score,
            "memory_stored": stored,
            "score_reason": reason,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memories/{user_id}")
async def get_memories(user_id: str):
    try:
        all_memories = memory.get_all(filters={"user_id": user_id})
        results = all_memories.get("results", all_memories) if isinstance(all_memories, dict) else all_memories
        return {"memories": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories/{user_id}/{memory_id}")
async def delete_memory(user_id: str, memory_id: str):
    try:
        memory.delete(memory_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories/{user_id}")
async def clear_memories(user_id: str):
    try:
        memory.delete_all(user_id=user_id)
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}
