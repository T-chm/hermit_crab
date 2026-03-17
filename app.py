#!/usr/bin/env python3
"""
Hermit Crab - Always-on local voice assistant
Whisper STT + Ollama LLM + Web UI
"""

import asyncio
import io
import json
import re
import time
import uuid
import warnings
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
import uvicorn
import whisper
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydub import AudioSegment

from tools import TOOLS, execute_tool

warnings.filterwarnings("ignore", category=FutureWarning)

# Persistent HTTP client (created on startup, reused for all Ollama calls)
_ollama_client: httpx.AsyncClient | None = None
_cached_index_html: str | None = None

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434"
DEFAULT_LLM = "qwen3.5:4b"
DEFAULT_WHISPER = "base"
SYSTEM_PROMPT = (
    "You are Hermit Crab Real Estate Edition, an AI assistant for real estate agents. "
    "You help with client meeting preparation, property research, and daily tasks. "
    "Keep responses brief and conversational unless the user asks for detail. "
    "IMPORTANT: Only use tools when the user EXPLICITLY asks you to perform an action. "
    "Never call tools for greetings, questions, or general conversation.\n"
    "TOOL GUIDANCE:\n"
    "- weather: 'what's the weather in London', 'forecast for Tokyo'. Use brief "
    "for quick checks, current for detail, forecast for multi-day.\n"
    "- reminders: 'remind me to follow up with the Doe family', 'show today's tasks'. "
    "Use add with title and due date.\n"
    "- notes: 'take a note about the Oak Lane showing', 'list my notes'. "
    "Use create with title and body.\n"
    "- gmail: 'check my email', 'search emails from John Doe'.\n"
    "- calendar: 'what's on my schedule', 'tomorrow's showings'."
)
MAX_HISTORY = 50  # trim oldest messages beyond this

# Lean prompt for follow-up after tool execution (no tool guidance needed)
FOLLOWUP_PROMPT = (
    "You are Hermit Crab, a helpful and concise voice assistant. "
    "Summarize the tool result naturally and briefly for the user. "
    "IMPORTANT: Report exactly what happened. If the tool failed or returned an error, "
    "tell the user honestly — never fabricate a success or invent actions you didn't take."
)

# ---------------------------------------------------------------------------
# Memory Config
# ---------------------------------------------------------------------------
MEMORY_DIR = Path.home() / ".hermit_crab"
COMPACT_WORKING_THRESHOLD = 40  # compact when history exceeds this
COMPACT_WORKING_KEEP = 20       # keep this many recent messages after compaction
FACT_EXTRACT_INTERVAL = 10      # extract facts every N messages
MAX_CORE_FACTS = 30             # compact core facts above this
MAX_SESSIONS = 20               # keep this many session files on disk

WORKING_COMPACT_PROMPT = (
    "Summarize this conversation in 3-5 sentences. Preserve:\n"
    "- Key information exchanged (questions asked, answers given)\n"
    "- Actions taken (tool calls, their results)\n"
    "- User preferences or context revealed\n"
    "Be concise but keep enough detail to continue the conversation naturally."
)

FACT_EXTRACT_PROMPT = (
    "Extract durable facts about the user from this conversation excerpt. "
    "Only include things worth remembering across sessions:\n"
    "- Name, location, language preferences\n"
    "- Habits, routines, interests\n"
    "- People they mention, relationships\n"
    "- Tool/service preferences (e.g. prefers Spotify)\n\n"
    "Return ONLY a JSON array of short strings. "
    "Return [] if nothing notable. No explanation."
)

FACT_COMPACT_PROMPT = (
    "Merge and deduplicate these user facts. Rules:\n"
    "- Combine related items into one (e.g. 'lives in London' + 'city is London' → 'Lives in London')\n"
    "- If two facts contradict, keep the one marked (newer)\n"
    "- Remove trivial or one-time items\n"
    "- Keep max 20 items\n\n"
    "Return ONLY a JSON array of strings. No explanation."
)

SESSION_SUMMARY_PROMPT = (
    "Summarize this conversation session in 1-2 sentences. "
    "Focus on what was accomplished and any notable user preferences shown."
)

# ---------------------------------------------------------------------------
# Agent Mode Config
# ---------------------------------------------------------------------------
MAX_AGENT_STEPS = 10

AGENT_PLAN_PROMPT = (
    "You are Hermit Crab in autonomous agent mode. "
    "Break the following goal into a short numbered plan (2-6 concrete steps). "
    "Each step should map to one tool call or one clear action.\n"
    "Format your response EXACTLY as:\n"
    "PLAN:\n1. First step\n2. Second step\n...\n\n"
    "Available tools and when to use them:\n" + SYSTEM_PROMPT.split("TOOL GUIDANCE:\n")[-1]
)

AGENT_STEP_PROMPT = (
    "You are Hermit Crab executing step {step} of {total} in an autonomous plan.\n"
    "GOAL: {goal}\n"
    "CURRENT STEP: {description}\n\n"
    "Previous results:\n{context}\n\n"
    "Execute this step now using the appropriate tool. "
    "Be concise in your response."
)

AGENT_EVALUATE_PROMPT = (
    "You just completed step {step} of {total}.\n"
    "GOAL: {goal}\n"
    "Step result: {result}\n"
    "Remaining steps: {remaining}\n\n"
    "Reply with exactly one of:\n"
    "CONTINUE - proceed to next step as planned\n"
    "REVISE: 1. new step 1\\n2. new step 2 - replace remaining steps\n"
    "DONE: summary of what was accomplished - goal is fully achieved\n"
    "FAIL: reason - goal cannot be completed"
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Hermit Crab")
whisper_model = None


@app.on_event("startup")
async def startup():
    global whisper_model, _ollama_client, _cached_index_html
    print(f"Loading Whisper '{DEFAULT_WHISPER}' model...")
    whisper_model = whisper.load_model(DEFAULT_WHISPER)
    # Persistent connection pool for all Ollama calls
    _ollama_client = httpx.AsyncClient(
        base_url=OLLAMA_URL,
        timeout=httpx.Timeout(300.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )
    # Pre-warm: tell Ollama to keep model loaded
    try:
        await _ollama_client.post("/api/chat", json={
            "model": DEFAULT_LLM, "messages": [], "keep_alive": "10m",
        })
    except Exception:
        pass
    # Cache index.html
    html_path = Path(__file__).parent / "static" / "index.html"
    _cached_index_html = html_path.read_text()
    print("Whisper model loaded. Ready.")


@app.on_event("shutdown")
async def shutdown():
    global _ollama_client
    if _ollama_client:
        await _ollama_client.aclose()
        _ollama_client = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def convert_and_transcribe(audio_bytes: bytes) -> str:
    """Convert audio to float32 numpy array in-memory, transcribe with Whisper."""
    # Decode audio in-memory (pydub auto-detects format from bytes)
    audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    # Convert to float32 numpy array (what Whisper expects)
    samples = np.frombuffer(audio.raw_data, dtype=np.int16).astype(np.float32) / 32768.0
    result = whisper_model.transcribe(samples)
    return result["text"].strip()


CLASSIFY_PROMPT = (
    "Rate the thinking complexity needed for the following user message.\n"
    "Reply with ONLY one word:\n"
    "  NONE — greetings, tool requests, simple facts, commands\n"
    "  LIGHT — explanations, comparisons, opinions, light reasoning\n"
    "  DEEP — multi-step math, coding, debugging, detailed analysis\n"
    "One word only."
)

# Thinking budget per complexity tier (num_predict = thinking + response tokens)
_THINK_BUDGET = {"NONE": 0, "LIGHT": 2048, "DEEP": 16384}


# Per-tool keyword routing — only send matching tool definitions to save TTFT
_TOOL_KEYWORD_MAP = {
    # --- Real Estate tools ---
    "client_brief": [
        "prep me", "brief me", "meeting with", "showing with",
        "prepare for", "client brief", "meeting prep",
        "prep for my", "ready for my",
    ],
    "client_memory": [
        "client", "clients", "ingest", "conversations", "transcripts",
        "wechat", "preferences", "dealbreaker", "must-have",
        "property history", "client profile", "import conversations",
    ],
    # --- Retained general tools ---
    "weather": [
        "weather", "temperature", "forecast", "rain", "sunny", "snow", "wind", "humid",
        "degrees", "celsius", "fahrenheit",
    ],
    "reminders": [
        "remind", "reminder", "alarm", "timer", "task", "todo",
        "due", "deadline", "follow up",
    ],
    "notes": [
        "note", "notes", "write down", "jot down", "save this", "take a note",
    ],
    "gmail": [
        "email", "emails", "inbox", "unread", "gmail", "mail",
        "send email", "send an email", "compose", "check mail",
    ],
    "calendar": [
        "calendar", "schedule", "meeting", "meetings", "agenda",
        "event", "events", "appointment", "free", "busy", "booked",
        "what's on", "what do i have", "showing", "showings",
    ],
}

# Build lookup: tool_name -> TOOLS entry
_TOOLS_BY_NAME = {t["function"]["name"]: t for t in TOOLS}


def _select_tools(text: str) -> list:
    """Return only the tool definitions whose keywords match the user message.
    Returns [] for pure conversation (saves ~5s TTFT)."""
    lower = text.lower()
    matched = []
    for tool_name, keywords in _TOOL_KEYWORD_MAP.items():
        if any(kw in lower for kw in keywords):
            defn = _TOOLS_BY_NAME.get(tool_name)
            if defn:
                matched.append(defn)
    return matched


# Tools with rich UI cards — skip the follow-up LLM text response
_RICH_UI_TOOLS = {"client_brief", "gmail", "calendar"}


# ---------------------------------------------------------------------------
# Direct tool dispatch — bypass first LLM call for obvious tool requests
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Direct dispatch regexes
# ---------------------------------------------------------------------------
_WEATHER_RE = re.compile(
    r"(?:weather|temperature|forecast|how(?:'s| is) (?:the |it )?\w*(?:weather|outside))"
    r"\s+(?:in|for|at|of)\s+(.+)",
    re.IGNORECASE,
)
_WEATHER_RE2 = re.compile(
    r"\b(?:in|for|at)\s+(.+?)\s+(?:weather|temperature|forecast)\b",
    re.IGNORECASE,
)
_REMIND_RE = re.compile(
    r"remind\s+(?:me\s+)?(?:to\s+)?(.+?)(?:\s+(?:at|by|on|tomorrow|today|tonight)\s*(.*))?$",
    re.IGNORECASE,
)


def _extract_memory_location(memory: "MemoryManager | None") -> str:
    """Try to extract user's location from stored memory facts."""
    if not memory:
        return ""
    for fact in memory.core_facts:
        fl = fact.lower()
        if "location" in fl or "live" in fl or "city" in fl or "from" in fl:
            cm = re.search(r"(?::\s*|in\s+|from\s+)(.+)", fl)
            if cm:
                return cm.group(1).strip()
    return ""


def _try_direct_dispatch(text: str, memory: "MemoryManager | None" = None) -> tuple[str, dict] | None:
    """Try to extract a direct tool call from the user message without LLM.
    Returns (tool_name, args) or None if ambiguous."""
    lower = text.lower().strip()
    clean = lower.rstrip("?.!")

    # === Client Brief (highest priority) ===
    m = re.search(
        r"\b(?:prep|prepare|brief)\s+(?:me\s+)?(?:for\s+)?(?:my\s+)?"
        r"(?:meeting|showing|appointment)\s+(?:with\s+)?(.+?)(?:\s+at\s+(.+))?$",
        lower,
    )
    if m:
        client = m.group(1).strip().rstrip("?.!")
        address = (m.group(2) or "").strip().rstrip("?.!")
        args = {"client_name": client}
        if address:
            args["address"] = address
        return ("client_brief", args)

    # "brief me on <client>"
    m = re.search(r"\bbrief\s+(?:me\s+)?(?:on|about)\s+(.+)", lower)
    if m:
        client = m.group(1).strip().rstrip("?.!")
        return ("client_brief", {"client_name": client})

    # === Client Memory ===
    if re.search(r"\b(?:ingest|import|process)\s+(?:my\s+)?(?:wechat|weixin)\b", lower):
        return ("client_memory", {"action": "ingest_wechat"})
    if re.search(r"\b(?:ingest|import|process)\s+(?:my\s+)?(?:conversations?|transcripts?|messages?)\b", lower):
        return ("client_memory", {"action": "ingest_wechat"})
    if re.search(r"\b(?:list|show)\s+(?:my\s+)?(?:all\s+)?clients?\b", lower):
        return ("client_memory", {"action": "list_clients"})
    m = re.search(r"\b(?:show|tell)\s+(?:me\s+)?(?:about\s+)?(.+?)(?:'s|s')\s+(?:profile|preferences?|history|info)\b", lower)
    if m:
        return ("client_memory", {"action": "query", "client_name": m.group(1).strip()})

    # === Weather ===
    m = _WEATHER_RE.search(lower)
    if not m:
        m = _WEATHER_RE2.search(lower)
    if m:
        location = m.group(1).strip().rstrip("?.!")
        if location and len(location) > 1:
            detail = "forecast" if "forecast" in lower else "brief"
            return ("weather", {"location": location, "detail": detail})

    if re.search(r"\b(?:weather|temperature|forecast)\b", lower):
        location = _extract_memory_location(memory)
        detail = "forecast" if "forecast" in lower else "brief"
        return ("weather", {"location": location, "detail": detail})

    # === Reminders ===
    # "remind me to X [tomorrow/today/at time]"
    m = _REMIND_RE.search(lower)
    if m:
        title = m.group(1).strip().rstrip("?.!")
        due_raw = (m.group(2) or "").strip().rstrip("?.!")
        due = ""
        if "tomorrow" in (due_raw or lower):
            due = "tomorrow"
        elif "today" in (due_raw or lower) or "tonight" in (due_raw or lower):
            due = "today"
        elif due_raw:
            due = due_raw
        args = {"action": "add", "title": title}
        if due:
            args["due"] = due
        return ("reminders", args)

    # "show/list/what are my reminders [today/tomorrow/this week]"
    if re.search(r"\b(?:show|list|what(?:'s| are))\s+(?:my\s+)?(?:today'?s?\s+)?(?:reminders|tasks|todos)\b", lower):
        if "tomorrow" in lower:
            return ("reminders", {"action": "tomorrow"})
        if "week" in lower:
            return ("reminders", {"action": "week"})
        if "overdue" in lower:
            return ("reminders", {"action": "overdue"})
        if "all" in lower:
            return ("reminders", {"action": "all"})
        return ("reminders", {"action": "today"})

    # === Notes ===
    # "take a note: X" / "note: X" / "jot down X"
    m = re.search(r"\b(?:take a note|note|jot down|write down|save this)[:\s]+(.+)", lower)
    if m:
        body = m.group(1).strip().rstrip("?.!")
        title = body[:50].split(".")[0]  # first sentence or 50 chars
        return ("notes", {"action": "create", "title": title, "body": body})

    # "find/search my notes about X"
    m = re.search(r"\b(?:find|search|look for)\s+(?:my\s+)?(?:notes?\s+)?(?:about|on|for)\s+(.+)", lower)
    if m:
        return ("notes", {"action": "search", "query": m.group(1).strip().rstrip("?.!")})

    # "list my notes"
    if re.search(r"\blist\s+(?:my\s+)?(?:all\s+)?notes\b", lower):
        return ("notes", {"action": "list"})

    # === Gmail ===
    # "check my email" / "any new emails" / "show my inbox" / "unread emails"
    if re.search(r"\b(?:check|show|any|read|open)\s+(?:my\s+)?(?:email|emails|inbox|mail|gmail)\b", lower):
        return ("gmail", {"action": "unread"})
    if re.search(r"\b(?:unread|new)\s+(?:email|emails|mail)\b", lower):
        return ("gmail", {"action": "unread"})
    # "search emails for X" / "find email from X" / "emails about X"
    m = re.search(r"\b(?:search|find|look for)\s+(?:my\s+)?(?:email|emails|mail)\s+(?:about|from|for|regarding)\s+(.+)", lower)
    if m:
        return ("gmail", {"action": "search", "query": m.group(1).strip().rstrip("?.!")})
    m = re.search(r"\b(?:email|emails|mail)\s+(?:about|from|regarding)\s+(.+)", lower)
    if m:
        return ("gmail", {"action": "search", "query": m.group(1).strip().rstrip("?.!")})
    # "send an email to X about Y" / "email X about Y"
    m = re.search(r"\b(?:send\s+(?:an?\s+)?email|email)\s+(?:to\s+)?(\S+@\S+)\s+(?:about|subject|saying)\s+(.+)", lower)
    if m:
        return ("gmail", {"action": "send", "to": m.group(1), "subject": m.group(2).strip().rstrip("?.!")})

    # === Calendar ===
    # "what's on my calendar" / "my schedule" / "my agenda" / "what do I have today"
    if re.search(r"\b(?:what(?:'s|s| is| do i have)\s+on\s+(?:my\s+)?(?:calendar|schedule))\b", lower):
        return ("calendar", {"action": "today"})
    if re.search(r"\b(?:my|show|today'?s?)\s+(?:schedule|agenda|calendar)\b", lower):
        return ("calendar", {"action": "today"})
    if re.search(r"\bwhat\s+(?:do i|meetings|events)\s+(?:have\s+)?(?:today|this morning|this afternoon)\b", lower):
        return ("calendar", {"action": "today"})
    # "what's on tomorrow" / "tomorrow's schedule"
    if re.search(r"\b(?:tomorrow|tmr)(?:'s)?\s+(?:schedule|agenda|calendar|meetings|events)\b", lower):
        return ("calendar", {"action": "tomorrow"})
    if re.search(r"\bwhat\s+(?:do i have|is)\s+(?:on\s+)?tomorrow\b", lower):
        return ("calendar", {"action": "tomorrow"})
    # "this week's schedule" / "events this week"
    if re.search(r"\b(?:this\s+)?week(?:'s)?\s+(?:schedule|agenda|calendar|events|meetings)\b", lower):
        return ("calendar", {"action": "week"})
    if re.search(r"\b(?:schedule|events|meetings|agenda)\s+(?:this|for the)\s+week\b", lower):
        return ("calendar", {"action": "week"})
    # "create an event" / "schedule a meeting" / "add to calendar: X"
    m = re.search(r"\b(?:create|schedule|add|set up|book)\s+(?:an?\s+)?(?:event|meeting|appointment|calendar entry)(?:\s*:?\s+(.+))?", lower)
    if m and m.group(1):
        return ("calendar", {"action": "create", "title": m.group(1).strip().rstrip("?.!")})
    elif m:
        return ("calendar", {"action": "create", "title": ""})


    return None


async def classify_thinking_budget(user_text: str, model: str) -> int:
    """Quick non-thinking LLM call to decide how much thinking budget the query needs.
    Returns num_predict cap (0 = no thinking)."""
    try:
        resp = await _ollama_client.post(
            "/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "options": {"num_predict": 4},
            },
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        resp.raise_for_status()
        answer = resp.json().get("message", {}).get("content", "").strip().upper()
        for tier in ("DEEP", "LIGHT", "NONE"):
            if tier in answer:
                return _THINK_BUDGET[tier]
        # Backward compat: YES → LIGHT, NO → NONE
        if answer.startswith("YES"):
            return _THINK_BUDGET["LIGHT"]
        return 0
    except Exception:
        return 0  # default to no thinking on error


async def _stream_response(ws: WebSocket, client: httpx.AsyncClient,
                           messages: list, model: str, think_budget: int = 0) -> str:
    """Stream a single Ollama call, forwarding tokens to the WebSocket.
    think_budget: 0 = no thinking, >0 = thinking enabled with num_predict cap.
    Returns the full accumulated response text."""
    payload = {"model": model, "messages": messages, "stream": True, "keep_alive": "10m"}
    if think_budget <= 0:
        payload["think"] = False
    else:
        payload["options"] = {"num_predict": think_budget}

    async with client.stream(
        "POST", "/api/chat", json=payload
    ) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            await ws.send_json(
                {"type": "error", "text": f"Ollama {resp.status_code}: {body.decode()[:200]}"}
            )
            return ""

        full = ""
        is_thinking = False
        async for line in resp.aiter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            m = chunk.get("message", {})

            thinking = m.get("thinking", "")
            if thinking:
                if not is_thinking:
                    is_thinking = True
                    await ws.send_json({"type": "thinking_start"})
                await ws.send_json({"type": "thinking_token", "token": thinking})

            token = m.get("content", "")
            if token:
                if is_thinking:
                    is_thinking = False
                    await ws.send_json({"type": "thinking_done"})
                full += token
                await ws.send_json({"type": "llm_token", "token": token})

            if chunk.get("done"):
                if is_thinking:
                    await ws.send_json({"type": "thinking_done"})
                break

    return full


async def stream_ollama(ws: WebSocket, history: list, model: str,
                        think_budget: int = 0, memory: "MemoryManager | None" = None):
    """Single streaming call with tools. Only includes tool definitions when
    the user message likely needs them (saves ~5s TTFT on conversational turns)."""
    # Only send tool definitions that match the user's message (saves ~5s TTFT)
    last_user = next(
        (m["content"] for m in reversed(history) if m.get("role") == "user"), ""
    )
    matched_tools = _select_tools(last_user)

    # Use brief memory (facts only, skip sessions) when tools are involved
    system = SYSTEM_PROMPT
    if memory:
        mem_ctx = memory.build_context(brief=bool(matched_tools))
        if mem_ctx:
            system = system + "\n\n" + mem_ctx
    messages = [{"role": "system", "content": system}] + history

    t0 = time.monotonic()
    await ws.send_json({"type": "llm_start"})

    try:
        client = _ollama_client

        # --- Fast path: direct dispatch for obvious tool requests (saves ~3.5s) ---
        direct = _try_direct_dispatch(last_user, memory) if matched_tools else None
        if direct:
            tool_name, tool_args = direct
            print(f"[perf] direct_dispatch: {tool_name}({tool_args})", flush=True)
            await ws.send_json({"type": "tool_call", "name": tool_name, "args": tool_args})
            await ws.send_json({"type": "status", "text": f"Running {tool_name}..."})
            tool_result = await asyncio.to_thread(execute_tool, tool_name, tool_args)
            history.append({"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": tool_name, "arguments": tool_args}}
            ]})
            history.append({"role": "tool", "content": tool_result})
            await ws.send_json({
                "type": "tool_result", "name": tool_name,
                "args": tool_args, "result": tool_result,
            })
            if tool_name in _RICH_UI_TOOLS:
                # Rich UI card speaks for itself — no follow-up text needed
                full = ""
                history.append({"role": "assistant", "content": full})
                t_total = time.monotonic() - t0
                await ws.send_json({
                    "type": "llm_done", "text": full,
                    "timing": {"first_token_ms": round(t_total * 1000), "total_ms": round(t_total * 1000)},
                })
                print(f"[perf] direct_dispatch(rich_ui): {tool_name} total={t_total:.2f}s", flush=True)
                return
            # Non-rich tools: single LLM call to format the response (lean prompt, no tools)
            # Use a plain user message with tool result inlined — avoids "role: tool"
            # parsing issues across different model families and keeps prompt small.
            await ws.send_json({"type": "status", "text": "Composing response..."})
            last_user = next(
                (m["content"] for m in reversed(history) if m.get("role") == "user"), ""
            )
            messages = [
                {"role": "system", "content": FOLLOWUP_PROMPT},
                {"role": "user", "content": (
                    f"User asked: {last_user}\n"
                    f"Tool '{tool_name}' returned:\n{tool_result}\n"
                    "Summarize this naturally for the user."
                )},
            ]
            first_token_time = None
            full = await _stream_response(ws, client, messages, model, think_budget)
            history.append({"role": "assistant", "content": full})
            t_total = time.monotonic() - t0
            t_first = (first_token_time or t_total) - t0 if first_token_time else t_total
            await ws.send_json({
                "type": "llm_done", "text": full,
                "timing": {"first_token_ms": round(t_total * 1000), "total_ms": round(t_total * 1000)},
            })
            print(f"[perf] first_token={t_total:.2f}s total={t_total:.2f}s tokens={len(full.split())} tools=direct:{tool_name}", flush=True)
            return

        # --- Normal path ---
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": "10m",
        }
        if matched_tools:
            payload["tools"] = matched_tools
        if think_budget <= 0:
            payload["think"] = False
        else:
            payload["options"] = {"num_predict": think_budget}

        first_token_time = None
        async with client.stream("POST", "/api/chat", json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                await ws.send_json(
                    {"type": "error", "text": f"Ollama {resp.status_code}: {body.decode()[:200]}"}
                )
                return

            full = ""
            is_thinking = False
            tool_calls = []

            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                m = chunk.get("message", {})

                tc = m.get("tool_calls")
                if tc:
                    tool_calls.extend(tc)

                thinking = m.get("thinking", "")
                if thinking:
                    if not is_thinking:
                        is_thinking = True
                        if not first_token_time:
                            first_token_time = time.monotonic()
                        await ws.send_json({"type": "thinking_start"})
                    await ws.send_json({"type": "thinking_token", "token": thinking})

                token = m.get("content", "")
                if token:
                    if is_thinking:
                        is_thinking = False
                        await ws.send_json({"type": "thinking_done"})
                    if not first_token_time:
                        first_token_time = time.monotonic()
                    full += token
                    await ws.send_json({"type": "llm_token", "token": token})

                if chunk.get("done"):
                    if is_thinking:
                        await ws.send_json({"type": "thinking_done"})
                    break

        # --- If tool calls were made, execute and get final response ---
        if tool_calls:
            clean_calls = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                clean_calls.append({
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", {}),
                    }
                })
            history.append({"role": "assistant", "content": "", "tool_calls": clean_calls})

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                tool_args = fn.get("arguments", {})

                await ws.send_json({
                    "type": "tool_call",
                    "name": tool_name,
                    "args": tool_args,
                })

                tool_result = await asyncio.to_thread(execute_tool, tool_name, tool_args)
                history.append({"role": "tool", "content": tool_result})

                await ws.send_json({
                    "type": "tool_result",
                    "name": tool_name,
                    "args": tool_args,
                    "result": tool_result,
                })

            # Check if all executed tools have rich UI — if so, skip follow-up text
            executed_names = {tc.get("function", {}).get("name", "") for tc in tool_calls}
            if executed_names and executed_names <= _RICH_UI_TOOLS:
                pass  # rich UI cards speak for themselves
            else:
                # Stream follow-up with lean prompt — inline tool results as plain
                # user message to avoid "role: tool" issues across model families.
                await ws.send_json({"type": "status", "text": "Composing response..."})
                last_user = next(
                    (m["content"] for m in reversed(history) if m.get("role") == "user"), ""
                )
                # Collect all tool results from the end of history
                tool_summary_parts = []
                for msg in history:
                    if msg.get("role") == "tool":
                        tool_summary_parts.append(msg["content"])
                tool_summary = "\n".join(tool_summary_parts[-len(tool_calls):])
                messages = [
                    {"role": "system", "content": FOLLOWUP_PROMPT},
                    {"role": "user", "content": (
                        f"User asked: {last_user}\n"
                        f"Tool results:\n{tool_summary}\n"
                        "Summarize this naturally for the user."
                    )},
                ]
                full = await _stream_response(ws, client, messages, model, think_budget)

        history.append({"role": "assistant", "content": full})
        t_total = time.monotonic() - t0
        t_first = (first_token_time - t0) if first_token_time else t_total
        await ws.send_json({
            "type": "llm_done", "text": full,
            "timing": {
                "first_token_ms": round(t_first * 1000),
                "total_ms": round(t_total * 1000),
            },
        })
        tool_names = [t["function"]["name"] for t in matched_tools] if matched_tools else []
        print(f"[perf] first_token={t_first:.2f}s total={t_total:.2f}s tokens={len(full.split())} tools={tool_names or 'none'}", flush=True)

    except httpx.ConnectError:
        await ws.send_json(
            {"type": "error", "text": "Cannot connect to Ollama. Run: ollama serve"}
        )
    except Exception as e:
        await ws.send_json({"type": "error", "text": f"Ollama error: {e}"})


# ---------------------------------------------------------------------------
# Agent Mode
# ---------------------------------------------------------------------------
def _parse_plan(text: str) -> list[str]:
    """Extract numbered steps from LLM plan output."""
    steps = re.findall(r"^\s*\d+[.)]\s*(.+)", text, re.MULTILINE)
    return steps if steps else [text.strip()]


async def _agent_llm_call(
    ws: WebSocket, messages: list, model: str,
    stop_event: asyncio.Event, step: int,
) -> tuple[str, list]:
    """Single LLM call for an agent step. Streams tokens as agent_token,
    handles tool calls, returns (response_text, tool_results)."""
    tool_results = []
    client = _ollama_client
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "tools": TOOLS,
        "think": False,
        "keep_alive": "10m",
    }

    async with client.stream("POST", "/api/chat", json=payload) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            return f"Error: Ollama {resp.status_code}: {body.decode()[:200]}", []

        full = ""
        tool_calls = []

        async for line in resp.aiter_lines():
            if not line or stop_event.is_set():
                break
            chunk = json.loads(line)
            m = chunk.get("message", {})

            tc = m.get("tool_calls")
            if tc:
                tool_calls.extend(tc)

            token = m.get("content", "")
            if token:
                full += token
                await ws.send_json({"type": "agent_token", "step": step, "token": token})

            if chunk.get("done"):
                break

    if stop_event.is_set():
        return full, []

    # Handle tool calls
    if tool_calls:
        clean_calls = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            clean_calls.append({
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", {}),
                }
            })
        messages.append({"role": "assistant", "content": "", "tool_calls": clean_calls})

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", {})

            await ws.send_json({
                "type": "agent_tool_call",
                "step": step,
                "name": tool_name,
                "args": tool_args,
            })

            tool_result = await asyncio.to_thread(execute_tool, tool_name, tool_args)
            messages.append({"role": "tool", "content": tool_result})
            tool_results.append({"name": tool_name, "result": tool_result})

            await ws.send_json({
                "type": "agent_tool_result",
                "step": step,
                "name": tool_name,
                "args": tool_args,
                "result": tool_result,
            })

        # Follow-up response after tool execution
        follow_payload = {
            "model": model, "messages": messages,
            "stream": True, "think": False, "keep_alive": "10m",
        }
        full = ""
        async with client.stream("POST", "/api/chat", json=follow_payload) as resp:
            if resp.status_code == 200:
                async for line in resp.aiter_lines():
                    if not line or stop_event.is_set():
                        break
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        full += token
                        await ws.send_json({"type": "agent_token", "step": step, "token": token})
                    if chunk.get("done"):
                        break

    return full, tool_results


async def _agent_quick_call(model: str, system: str, user: str) -> str:
    """Non-streaming LLM call for planning/evaluation."""
    try:
        resp = await _ollama_client.post(
            "/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "think": False,
                "keep_alive": "10m",
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Tiered Memory System
# ---------------------------------------------------------------------------
def _format_messages_for_summary(msgs: list) -> str:
    """Convert history entries to readable text for LLM summarization."""
    parts = []
    for m in msgs:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "tool":
            parts.append(f"[Tool result: {content[:150]}]")
        elif role == "assistant" and m.get("tool_calls"):
            calls = ", ".join(
                tc.get("function", {}).get("name", "?") for tc in m["tool_calls"]
            )
            parts.append(f"Assistant: [Called tools: {calls}]")
        elif content:
            parts.append(f"{role.title()}: {content}")
    return "\n".join(parts)


class MemoryManager:
    """Three-tier memory: working (RAM), sessions (disk), core facts (disk)."""

    def __init__(self):
        self.data_dir = MEMORY_DIR
        self.sessions_dir = self.data_dir / "sessions"
        self.memory_file = self.data_dir / "memory.json"

        # Tier 1: Working memory (current session summary of compacted messages)
        self.working_summary: str = ""

        # Tier 3: Core facts about the user
        self.core_facts: list[str] = []

        # Tier 2: Recent session summaries (loaded from disk)
        self.session_summaries: list[dict] = []

        # Tracking
        self.message_count: int = 0  # messages since last fact extraction
        self._compacting: bool = False

        self._load()

    def _load(self):
        """Load core facts and session summaries from disk."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.sessions_dir.mkdir(exist_ok=True)
        except OSError:
            return

        # Load core facts
        if self.memory_file.exists():
            try:
                data = json.loads(self.memory_file.read_text())
                self.core_facts = data.get("facts", [])
            except (json.JSONDecodeError, OSError):
                pass

        # Load recent session summaries
        try:
            session_files = sorted(self.sessions_dir.glob("*.json"), reverse=True)
            for sf in session_files[:MAX_SESSIONS]:
                try:
                    sd = json.loads(sf.read_text())
                    self.session_summaries.append(sd)
                except (json.JSONDecodeError, OSError):
                    continue
            self.session_summaries.reverse()  # oldest first
        except OSError:
            pass

    def _save_core(self):
        """Save core facts to disk."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.memory_file.write_text(json.dumps({
                "facts": self.core_facts,
                "last_updated": datetime.now().isoformat(),
            }, indent=2))
        except OSError:
            pass

    def build_context(self, brief: bool = False) -> str:
        """Build memory context string to inject into the system prompt.
        brief=True omits session summaries (for tool-call paths where speed matters)."""
        parts = []

        if self.core_facts:
            facts_str = "\n".join(f"- {f}" for f in self.core_facts[:MAX_CORE_FACTS])
            parts.append(f"WHAT YOU REMEMBER ABOUT THE USER:\n{facts_str}")

        if not brief and self.session_summaries:
            recent = self.session_summaries[-3:]
            sessions_str = "\n".join(
                f"- [{s.get('date', '?')}] {s.get('summary', '')}"
                for s in recent
            )
            parts.append(f"RECENT PAST SESSIONS:\n{sessions_str}")

        if self.working_summary:
            parts.append(
                f"EARLIER IN THIS CONVERSATION:\n{self.working_summary}"
            )

        return "\n\n".join(parts)

    def memory_status(self) -> dict:
        """Return current memory stats."""
        return {
            "facts_count": len(self.core_facts),
            "sessions_count": len(self.session_summaries),
            "working_summary": bool(self.working_summary),
        }

    async def compact_working(self, history: list, model: str):
        """Tier 1: Compress oldest messages when history gets long."""
        if len(history) <= COMPACT_WORKING_THRESHOLD or self._compacting:
            return
        self._compacting = True
        try:
            split = len(history) - COMPACT_WORKING_KEEP
            to_compress = history[:split]

            text = ""
            if self.working_summary:
                text = f"Previous context: {self.working_summary}\n\n"
            text += _format_messages_for_summary(to_compress)

            summary = await _agent_quick_call(
                model, WORKING_COMPACT_PROMPT, text
            )

            if summary and not summary.startswith("Error"):
                self.working_summary = summary
                history[:] = history[split:]
        finally:
            self._compacting = False

    async def extract_facts(self, history: list, model: str):
        """Tier 3: Extract durable facts from recent conversation."""
        self.message_count += 1
        if self.message_count < FACT_EXTRACT_INTERVAL:
            return

        self.message_count = 0

        # Take the last N messages for extraction
        recent = history[-FACT_EXTRACT_INTERVAL:]
        text = _format_messages_for_summary(recent)

        raw = await _agent_quick_call(model, FACT_EXTRACT_PROMPT, text)

        # Parse JSON array from response
        new_facts = _parse_json_array(raw)
        if not new_facts:
            return

        self.core_facts.extend(new_facts)

        # Compact if too many facts
        if len(self.core_facts) > MAX_CORE_FACTS:
            await self._compact_core(model)
        else:
            self._save_core()

    async def _compact_core(self, model: str):
        """Tier 3: Merge and deduplicate core facts."""
        facts_text = json.dumps(self.core_facts)
        raw = await _agent_quick_call(model, FACT_COMPACT_PROMPT, facts_text)
        merged = _parse_json_array(raw)
        if merged:
            self.core_facts = merged
        self._save_core()

    async def save_session(self, history: list, model: str):
        """Tier 2: Summarize current session and save to disk on disconnect."""
        if not history and not self.working_summary:
            return

        text = ""
        if self.working_summary:
            text = f"Earlier: {self.working_summary}\n\n"
        text += _format_messages_for_summary(history)

        if len(text.strip()) < 20:
            return

        summary = await _agent_quick_call(model, SESSION_SUMMARY_PROMPT, text)
        if not summary or summary.startswith("Error"):
            return

        # Also do a final fact extraction
        if history:
            all_text = _format_messages_for_summary(history)
            raw = await _agent_quick_call(model, FACT_EXTRACT_PROMPT, all_text)
            new_facts = _parse_json_array(raw)
            if new_facts:
                self.core_facts.extend(new_facts)
                if len(self.core_facts) > MAX_CORE_FACTS:
                    await self._compact_core(model)
                else:
                    self._save_core()

        # Save session file
        session_data = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "summary": summary,
        }

        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = self.sessions_dir / f"{ts}.json"
            filepath.write_text(json.dumps(session_data, indent=2))
        except OSError:
            pass

        self.session_summaries.append(session_data)

        # Prune old session files
        self._prune_sessions()

    def _prune_sessions(self):
        """Keep only the most recent MAX_SESSIONS session files."""
        try:
            files = sorted(self.sessions_dir.glob("*.json"))
            if len(files) > MAX_SESSIONS:
                for f in files[:-MAX_SESSIONS]:
                    f.unlink(missing_ok=True)
            self.session_summaries = self.session_summaries[-MAX_SESSIONS:]
        except OSError:
            pass

    def clear(self):
        """Wipe all memory."""
        self.core_facts.clear()
        self.session_summaries.clear()
        self.working_summary = ""
        self.message_count = 0

        # Clear disk
        try:
            if self.memory_file.exists():
                self.memory_file.unlink()
            for f in self.sessions_dir.glob("*.json"):
                f.unlink(missing_ok=True)
        except OSError:
            pass


def _parse_json_array(text: str) -> list[str]:
    """Extract a JSON array of strings from LLM output."""
    # Try to find JSON array in the response
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(item) for item in result if item]
        except json.JSONDecodeError:
            pass
    return []


async def run_agent_loop(
    ws: WebSocket, goal: str, model: str,
    stop_event: asyncio.Event, history: list,
):
    """Main autonomous agent loop: PLAN → ACT → EVALUATE → ITERATE."""
    agent_id = str(uuid.uuid4())[:8]

    try:
        await ws.send_json({"type": "agent_start", "agent_id": agent_id, "goal": goal})

        # --- PHASE 1: PLAN ---
        plan_text = await _agent_quick_call(model, AGENT_PLAN_PROMPT, goal)
        steps = _parse_plan(plan_text)

        if stop_event.is_set():
            await ws.send_json({"type": "agent_stopped", "agent_id": agent_id})
            return

        await ws.send_json({
            "type": "agent_plan",
            "agent_id": agent_id,
            "plan": plan_text,
            "steps": steps,
        })

        # --- PHASE 2: EXECUTE STEPS ---
        context_log = []  # Track results for context

        for i, step_desc in enumerate(steps):
            if stop_event.is_set():
                break
            if i >= MAX_AGENT_STEPS:
                break

            step_num = i + 1
            await ws.send_json({
                "type": "agent_step_start",
                "agent_id": agent_id,
                "step": step_num,
                "total": len(steps),
                "description": step_desc,
            })

            # Build messages for this step
            context_str = "\n".join(context_log[-5:]) if context_log else "(none yet)"
            step_system = AGENT_STEP_PROMPT.format(
                step=step_num, total=len(steps),
                goal=goal, description=step_desc, context=context_str,
            )
            messages = [
                {"role": "system", "content": step_system},
                {"role": "user", "content": f"Execute: {step_desc}"},
            ]

            # ACT
            response, tool_results = await _agent_llm_call(
                ws, messages, model, stop_event, step_num,
            )

            if stop_event.is_set():
                break

            # Build step result summary
            if tool_results:
                result_summary = "; ".join(
                    f"{tr['name']}: {tr['result'][:100]}" for tr in tool_results
                )
            else:
                result_summary = response[:200]
            context_log.append(f"Step {step_num} ({step_desc}): {result_summary}")

            await ws.send_json({
                "type": "agent_step_done",
                "agent_id": agent_id,
                "step": step_num,
                "summary": result_summary[:200],
            })

            # EVALUATE (skip for last step)
            if step_num < len(steps):
                remaining = "\n".join(
                    f"{j+1}. {s}" for j, s in enumerate(steps[i+1:])
                )
                eval_text = await _agent_quick_call(
                    model, AGENT_EVALUATE_PROMPT.format(
                        step=step_num, total=len(steps), goal=goal,
                        result=result_summary, remaining=remaining or "(none)",
                    ),
                    "Evaluate progress.",
                )

                if stop_event.is_set():
                    break

                upper = eval_text.upper()
                if upper.startswith("DONE"):
                    await ws.send_json({
                        "type": "agent_done",
                        "agent_id": agent_id,
                        "summary": eval_text.split(":", 1)[-1].strip() if ":" in eval_text else eval_text,
                        "steps_completed": step_num,
                    })
                    # Record in main history
                    history.append({"role": "user", "content": f"[Agent goal: {goal}]"})
                    history.append({"role": "assistant", "content": eval_text.split(":", 1)[-1].strip()})
                    return
                elif upper.startswith("REVISE"):
                    new_steps = _parse_plan(eval_text)
                    if new_steps:
                        steps[i+1:] = new_steps
                        await ws.send_json({
                            "type": "agent_plan_revised",
                            "agent_id": agent_id,
                            "steps": steps[i+1:],
                        })
                elif upper.startswith("FAIL"):
                    reason = eval_text.split(":", 1)[-1].strip() if ":" in eval_text else eval_text
                    await ws.send_json({
                        "type": "agent_error",
                        "agent_id": agent_id,
                        "text": f"Agent stopped: {reason}",
                    })
                    history.append({"role": "user", "content": f"[Agent goal: {goal}]"})
                    history.append({"role": "assistant", "content": f"Could not complete: {reason}"})
                    return

        # --- PHASE 3: FINAL SUMMARY ---
        if stop_event.is_set():
            await ws.send_json({"type": "agent_stopped", "agent_id": agent_id})
        else:
            summary = "\n".join(context_log)
            final = await _agent_quick_call(
                model,
                "Summarize what was accomplished in 2-3 sentences.",
                f"Goal: {goal}\nResults:\n{summary}",
            )
            await ws.send_json({
                "type": "agent_done",
                "agent_id": agent_id,
                "summary": final,
                "steps_completed": len(context_log),
            })
            history.append({"role": "user", "content": f"[Agent goal: {goal}]"})
            history.append({"role": "assistant", "content": final})

    except asyncio.CancelledError:
        try:
            await ws.send_json({"type": "agent_stopped", "agent_id": agent_id})
        except Exception:
            pass
    except Exception as e:
        try:
            await ws.send_json({"type": "agent_error", "agent_id": agent_id, "text": str(e)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/models")
async def list_models():
    """Return locally available Ollama models."""
    try:
        resp = await _ollama_client.get("/api/tags")
        resp.raise_for_status()
        models = resp.json().get("models", [])
        names = sorted(m["name"] for m in models)
        return {"models": names, "default": DEFAULT_LLM}
    except Exception:
        return {"models": [DEFAULT_LLM], "default": DEFAULT_LLM}


@app.get("/")
async def index():
    if _cached_index_html:
        return HTMLResponse(_cached_index_html)
    html = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html.read_text())


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    history: list[dict] = []
    audio_buffer = bytearray()
    model = DEFAULT_LLM
    auto_think = False  # off by default, user can toggle on
    agent_task: asyncio.Task | None = None
    agent_stop = asyncio.Event()
    memory = MemoryManager()

    # Send initial memory status
    await ws.send_json({"type": "memory_status", **memory.memory_status()})

    async def _post_response_work():
        """Run memory operations after each LLM response (background)."""
        try:
            await memory.compact_working(history, model)
            await memory.extract_facts(history, model)
            await ws.send_json({"type": "memory_status", **memory.memory_status()})
        except Exception:
            pass  # memory failures should never break the assistant

    def _post_response():
        """Fire-and-forget memory operations so they don't block the next response."""
        asyncio.create_task(_post_response_work())

    try:
        while True:
            msg = await ws.receive()

            # --- Binary: audio chunk ---
            if "bytes" in msg and msg["bytes"]:
                audio_buffer.extend(msg["bytes"])
                continue

            # --- Text: JSON command ---
            if "text" not in msg:
                continue

            data = json.loads(msg["text"])
            msg_type = data.get("type")

            if msg_type == "audio_end":
                if len(audio_buffer) < 1000:
                    audio_buffer.clear()
                    await ws.send_json({"type": "status", "text": "idle"})
                    continue

                raw = bytes(audio_buffer)
                audio_buffer.clear()

                await ws.send_json({"type": "status", "text": "Transcribing..."})
                t_stt = time.monotonic()
                text = await asyncio.to_thread(convert_and_transcribe, raw)
                t_stt = time.monotonic() - t_stt
                print(f"[perf] stt={t_stt:.2f}s", flush=True)

                if not text or len(text) < 2:
                    await ws.send_json({"type": "status", "text": "idle"})
                    continue

                await ws.send_json({"type": "transcription", "text": text})
                history.append({"role": "user", "content": text})

                # Trim history (hard cap, compaction handles the rest)
                if len(history) > MAX_HISTORY:
                    history[:] = history[-MAX_HISTORY:]

                # Auto-classify thinking budget
                think_budget = 0
                if auto_think:
                    await ws.send_json({"type": "status", "text": "Classifying..."})
                    think_budget = await classify_thinking_budget(text, model)
                    await ws.send_json({"type": "think_decision", "enabled": think_budget > 0, "budget": think_budget})
                await stream_ollama(ws, history, model, think_budget, memory)
                _post_response()

            elif msg_type == "text_input":
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue
                await ws.send_json({"type": "transcription", "text": user_text})
                history.append({"role": "user", "content": user_text})
                if len(history) > MAX_HISTORY:
                    history[:] = history[-MAX_HISTORY:]

                think_budget = 0
                if auto_think:
                    await ws.send_json({"type": "status", "text": "Classifying..."})
                    think_budget = await classify_thinking_budget(user_text, model)
                    await ws.send_json({"type": "think_decision", "enabled": think_budget > 0, "budget": think_budget})
                await stream_ollama(ws, history, model, think_budget, memory)
                _post_response()

            elif msg_type == "agent_start":
                goal = data.get("goal", "").strip()
                if not goal:
                    continue
                # Stop any running agent first
                if agent_task and not agent_task.done():
                    agent_stop.set()
                    agent_task.cancel()
                    try:
                        await agent_task
                    except (asyncio.CancelledError, Exception):
                        pass
                agent_stop.clear()
                agent_task = asyncio.create_task(
                    run_agent_loop(ws, goal, model, agent_stop, history)
                )

            elif msg_type == "agent_stop":
                if agent_task and not agent_task.done():
                    agent_stop.set()
                    agent_task.cancel()

            elif msg_type == "clear":
                history.clear()
                memory.working_summary = ""
                if agent_task and not agent_task.done():
                    agent_stop.set()
                    agent_task.cancel()
                await ws.send_json({"type": "cleared"})
                await ws.send_json({"type": "memory_status", **memory.memory_status()})

            elif msg_type == "clear_memory":
                memory.clear()
                await ws.send_json({"type": "memory_status", **memory.memory_status()})
                await ws.send_json({
                    "type": "status", "text": "Memory cleared"
                })

            elif msg_type == "get_memory":
                await ws.send_json({
                    "type": "memory_detail",
                    "facts": memory.core_facts,
                    "sessions": memory.session_summaries[-5:],
                    "working": memory.working_summary,
                })

            elif msg_type == "set_model":
                old_model = model
                model = data.get("model", DEFAULT_LLM)
                await ws.send_json({"type": "model_set", "model": model})
                # Unload old model to free VRAM, then pre-warm the new one
                try:
                    if old_model != model:
                        await _ollama_client.post("/api/chat", json={
                            "model": old_model, "messages": [], "keep_alive": "0",
                        })
                    await _ollama_client.post("/api/chat", json={
                        "model": model, "messages": [], "keep_alive": "10m",
                    })
                except Exception:
                    pass

            elif msg_type == "set_auto_think":
                auto_think = data.get("enabled", True)
                await ws.send_json({"type": "auto_think_set", "enabled": auto_think})

    except WebSocketDisconnect:
        if agent_task and not agent_task.done():
            agent_stop.set()
            agent_task.cancel()
        # Save session on disconnect
        try:
            await memory.save_session(history, model)
        except Exception:
            pass
    except Exception as e:
        if agent_task and not agent_task.done():
            agent_stop.set()
            agent_task.cancel()
        try:
            await memory.save_session(history, model)
        except Exception:
            pass
        try:
            await ws.send_json({"type": "error", "text": str(e)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
