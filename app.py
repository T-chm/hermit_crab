#!/usr/bin/env python3
"""
Hermit Crab - Always-on local voice assistant
Whisper STT + Ollama LLM + Web UI
"""

import asyncio
import json
import os
import tempfile
import warnings
from pathlib import Path

import httpx
import uvicorn
import whisper
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydub import AudioSegment

from tools import TOOLS, execute_tool

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434"
DEFAULT_LLM = "qwen3.5:4b"
DEFAULT_WHISPER = "base"
SYSTEM_PROMPT = (
    "You are Hermit Crab, a helpful and concise voice assistant running locally. "
    "Keep responses brief and conversational unless the user asks for detail. "
    "IMPORTANT: Only use tools when the user EXPLICITLY asks you to perform an action. "
    "Never call tools for greetings, questions, or general conversation.\n"
    "TOOL GUIDANCE:\n"
    "- music_control: 'play music', 'pause', 'skip'. Use play_artist for artists "
    "(e.g. 'play some Coldplay'), play_song with query+artist for specific songs "
    "(e.g. 'play Volcano from U2' → query='Volcano', artist='U2').\n"
    "- weather: 'what's the weather in London', 'forecast for Tokyo'. Use brief "
    "for quick checks, current for detail, forecast for multi-day.\n"
    "- smart_home: 'turn off the bedroom light', 'set living room to 50%', "
    "'make it red', 'activate the relax scene'.\n"
    "- reminders: 'remind me to call mom tomorrow', 'what are my reminders', "
    "'show today's tasks'. Use add with title and due date.\n"
    "- notes: 'take a note', 'find my note about recipes', 'list my notes'. "
    "Use create with title and body.\n"
    "- summarize: 'summarize this article/video' + URL. Handles web pages, "
    "PDFs, and YouTube videos.\n"
    "- messaging: 'text John I'm running late', 'read my messages', "
    "'show recent conversations'. Always confirm before sending."
)
MAX_HISTORY = 50  # trim oldest messages beyond this

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Hermit Crab")
whisper_model = None


@app.on_event("startup")
async def load_whisper():
    global whisper_model
    print(f"Loading Whisper '{DEFAULT_WHISPER}' model...")
    whisper_model = whisper.load_model(DEFAULT_WHISPER)
    print("Whisper model loaded. Ready.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def convert_and_transcribe(audio_bytes: bytes) -> str:
    """Convert webm audio to wav, transcribe with Whisper, clean up."""
    webm_path = None
    wav_path = None
    try:
        # Write raw audio bytes (could be webm, mp4, ogg depending on browser)
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as f:
            f.write(audio_bytes)
            webm_path = f.name

        # Convert to 16 kHz mono WAV via pydub (ffmpeg auto-detects format)
        audio = AudioSegment.from_file(webm_path)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        wav_path = webm_path + ".wav"
        audio.export(wav_path, format="wav")

        # Transcribe
        result = whisper_model.transcribe(wav_path)
        return result["text"].strip()
    finally:
        for p in (webm_path, wav_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


CLASSIFY_PROMPT = (
    "Does the following user message require complex reasoning, multi-step analysis, "
    "math, coding, debugging, detailed explanation, or comparison? "
    "Reply with ONLY the single word YES or NO, nothing else."
)


async def classify_needs_thinking(user_text: str, model: str) -> bool:
    """Quick non-thinking LLM call to decide if the query needs deep reasoning."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0)
        ) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": CLASSIFY_PROMPT},
                        {"role": "user", "content": user_text},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 4},
                },
            )
            resp.raise_for_status()
            answer = resp.json().get("message", {}).get("content", "").strip().upper()
            return answer.startswith("YES")
    except Exception:
        return False  # default to fast mode on error


async def _stream_response(ws: WebSocket, client: httpx.AsyncClient,
                           messages: list, model: str, think: bool) -> str:
    """Stream a single Ollama call, forwarding tokens to the WebSocket.
    Returns the full accumulated response text."""
    payload = {"model": model, "messages": messages, "stream": True}
    if not think:
        payload["think"] = False

    async with client.stream(
        "POST", f"{OLLAMA_URL}/api/chat", json=payload
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


async def stream_ollama(ws: WebSocket, history: list, model: str, think: bool = False):
    """Single streaming call with tools. If a tool call is detected in the
    first chunk, execute it and stream a follow-up response."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    await ws.send_json({"type": "llm_start"})

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=10.0)
        ) as client:

            # --- Single streaming call with tools ---
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "tools": TOOLS,
            }
            if not think:
                payload["think"] = False

            async with client.stream(
                "POST", f"{OLLAMA_URL}/api/chat", json=payload
            ) as resp:
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

                    # Check for tool calls (arrive in first chunk)
                    tc = m.get("tool_calls")
                    if tc:
                        tool_calls.extend(tc)

                    # Stream thinking tokens
                    thinking = m.get("thinking", "")
                    if thinking:
                        if not is_thinking:
                            is_thinking = True
                            await ws.send_json({"type": "thinking_start"})
                        await ws.send_json({"type": "thinking_token", "token": thinking})

                    # Stream content tokens
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

            # --- If tool calls were made, execute and get final response ---
            if tool_calls:
                # Clean tool calls for history (remove 'index' field from streaming format)
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

                # Stream the follow-up response (no tools this time)
                messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
                full = await _stream_response(ws, client, messages, model, think)

            history.append({"role": "assistant", "content": full})
            await ws.send_json({"type": "llm_done", "text": full})

    except httpx.ConnectError:
        await ws.send_json(
            {"type": "error", "text": "Cannot connect to Ollama. Run: ollama serve"}
        )
    except Exception as e:
        await ws.send_json({"type": "error", "text": f"Ollama error: {e}"})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
async def index():
    html = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html.read_text())


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    history: list[dict] = []
    audio_buffer = bytearray()
    model = DEFAULT_LLM
    auto_think = False  # off by default, user can toggle on

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
                text = await asyncio.to_thread(convert_and_transcribe, raw)

                if not text or len(text) < 2:
                    await ws.send_json({"type": "status", "text": "idle"})
                    continue

                await ws.send_json({"type": "transcription", "text": text})
                history.append({"role": "user", "content": text})

                # Trim history
                if len(history) > MAX_HISTORY:
                    history[:] = history[-MAX_HISTORY:]

                # Auto-classify thinking need
                think = False
                if auto_think:
                    await ws.send_json({"type": "status", "text": "Classifying..."})
                    think = await classify_needs_thinking(text, model)
                    await ws.send_json({"type": "think_decision", "enabled": think})
                await stream_ollama(ws, history, model, think)

            elif msg_type == "text_input":
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue
                await ws.send_json({"type": "transcription", "text": user_text})
                history.append({"role": "user", "content": user_text})
                if len(history) > MAX_HISTORY:
                    history[:] = history[-MAX_HISTORY:]

                think = False
                if auto_think:
                    await ws.send_json({"type": "status", "text": "Classifying..."})
                    think = await classify_needs_thinking(user_text, model)
                    await ws.send_json({"type": "think_decision", "enabled": think})
                await stream_ollama(ws, history, model, think)

            elif msg_type == "clear":
                history.clear()
                await ws.send_json({"type": "cleared"})

            elif msg_type == "set_model":
                model = data.get("model", DEFAULT_LLM)
                await ws.send_json({"type": "model_set", "model": model})

            elif msg_type == "set_auto_think":
                auto_think = data.get("enabled", True)
                await ws.send_json({"type": "auto_think_set", "enabled": auto_think})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "text": str(e)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
