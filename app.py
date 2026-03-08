#!/usr/bin/env python3
"""
Hermit Crab - Always-on local voice assistant
Whisper STT + Ollama LLM + Web UI
"""

import asyncio
import json
import os
import subprocess
import tempfile
import warnings
from pathlib import Path

import httpx
import uvicorn
import whisper
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydub import AudioSegment

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
    "IMPORTANT: Only use tools when the user EXPLICITLY asks you to perform an action "
    "(e.g. 'play music', 'pause', 'skip song'). Never call tools for greetings, "
    "questions, or general conversation."
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
# Tools
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "music_control",
            "description": "Control music playback on Apple Music or Spotify. ONLY use when the user explicitly asks to play, pause, skip, or get info about music. Do NOT call this for greetings or general conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "play", "pause", "next", "previous",
                            "current_track", "play_song", "play_artist", "play_album",
                            "artist_info", "album_info", "search",
                        ],
                        "description": (
                            "The music action to perform. "
                            "artist_info: list albums and songs by an artist in the library. "
                            "album_info: list tracks on an album. "
                            "search: search the library for a query and return matching tracks."
                        ),
                    },
                    "app": {
                        "type": "string",
                        "enum": ["spotify", "apple_music"],
                        "description": "Which music app to use. Default: apple_music",
                    },
                    "query": {
                        "type": "string",
                        "description": "Song name, artist name, or album name",
                    },
                },
                "required": ["action"],
            },
        },
    },
]


def _applescript(script: str) -> str:
    """Run an AppleScript via osascript and return output."""
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        return f"Error: {r.stderr.strip()}"
    return r.stdout.strip()


def _music_app_name(app: str) -> str:
    return "Spotify" if app == "spotify" else "Music"


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool call and return the result as a string."""
    if name != "music_control":
        return f"Unknown tool: {name}"

    action = args.get("action", "")
    app = args.get("app", "apple_music")
    query = args.get("query", "")
    app_name = _music_app_name(app)

    # Escape single quotes in query
    safe_query = query.replace("'", "'\\''") if query else ""

    if action == "play":
        _applescript(f'tell application "{app_name}" to play')
        return f"Resumed playback on {app_name}."

    elif action == "pause":
        _applescript(f'tell application "{app_name}" to pause')
        return f"Paused {app_name}."

    elif action == "next":
        _applescript(f'tell application "{app_name}" to next track')
        return f"Skipped to next track on {app_name}."

    elif action == "previous":
        _applescript(f'tell application "{app_name}" to previous track')
        return f"Went to previous track on {app_name}."

    elif action == "current_track":
        info = _applescript(
            f'tell application "{app_name}" to get '
            f'{{name of current track, artist of current track, album of current track}}'
        )
        if info.startswith("Error"):
            return "No track is currently playing."
        return f"Now playing on {app_name}: {info}"

    elif action == "play_song" and safe_query:
        if app == "spotify":
            # Spotify can't search via AppleScript — just play and let it resume
            _applescript(f'tell application "Spotify" to play')
            return f"Spotify doesn't support search via AppleScript. Resumed playback. Try searching in the Spotify app for '{query}'."
        else:
            result = _applescript(
                f'tell application "Music"\n'
                f'  set results to (search playlist "Library" for "{safe_query}" only songs)\n'
                f'  if (count of results) > 0 then\n'
                f'    play item 1 of results\n'
                f'    return name of current track & " by " & artist of current track\n'
                f'  else\n'
                f'    return "NOT_FOUND"\n'
                f'  end if\n'
                f'end tell'
            )
            if "NOT_FOUND" in result or result.startswith("Error"):
                return f"Could not find '{query}' in your Apple Music library."
            return f"Now playing: {result}"

    elif action == "play_artist" and safe_query:
        if app == "spotify":
            _applescript(f'tell application "Spotify" to play')
            return f"Spotify doesn't support search via AppleScript. Resumed playback."
        else:
            result = _applescript(
                f'tell application "Music"\n'
                f'  set results to (search playlist "Library" for "{safe_query}" only artists)\n'
                f'  if (count of results) > 0 then\n'
                f'    play item 1 of results\n'
                f'    return "Playing " & artist of current track\n'
                f'  else\n'
                f'    return "NOT_FOUND"\n'
                f'  end if\n'
                f'end tell'
            )
            if "NOT_FOUND" in result or result.startswith("Error"):
                return f"Could not find artist '{query}' in your Apple Music library."
            return result

    elif action == "play_album" and safe_query:
        if app == "spotify":
            _applescript(f'tell application "Spotify" to play')
            return f"Spotify doesn't support search via AppleScript. Resumed playback."
        else:
            result = _applescript(
                f'tell application "Music"\n'
                f'  set results to (search playlist "Library" for "{safe_query}" only albums)\n'
                f'  if (count of results) > 0 then\n'
                f'    play item 1 of results\n'
                f'    return "Playing album: " & album of current track\n'
                f'  else\n'
                f'    return "NOT_FOUND"\n'
                f'  end if\n'
                f'end tell'
            )
            if "NOT_FOUND" in result or result.startswith("Error"):
                return f"Could not find album '{query}' in your Apple Music library."
            return result

    elif action == "artist_info" and safe_query:
        if app == "spotify":
            return "Spotify library browsing is not supported via AppleScript."
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (every track of playlist "Library" whose artist contains "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set albumList to {{}}\n'
            f'  set songList to {{}}\n'
            f'  repeat with t in results\n'
            f'    set aName to album of t\n'
            f'    if aName is not in albumList then set end of albumList to aName\n'
            f'    if (count of songList) < 20 then\n'
            f'      set end of songList to (name of t & " (" & album of t & ")")\n'
            f'    end if\n'
            f'  end repeat\n'
            f'  set albumCount to count of albumList\n'
            f'  set songCount to count of results\n'
            f'  set output to "Artist: {safe_query}" & return & "Songs: " & songCount & ", Albums: " & albumCount & return & return & "Albums:" & return\n'
            f'  repeat with a in albumList\n'
            f'    set output to output & "- " & a & return\n'
            f'  end repeat\n'
            f'  set output to output & return & "Songs (first 20):" & return\n'
            f'  repeat with s in songList\n'
            f'    set output to output & "- " & s & return\n'
            f'  end repeat\n'
            f'  return output\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find artist '{query}' in your Apple Music library."
        return result

    elif action == "album_info" and safe_query:
        if app == "spotify":
            return "Spotify library browsing is not supported via AppleScript."
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (every track of playlist "Library" whose album contains "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set output to "Album: " & album of (item 1 of results) & return & "Artist: " & artist of (item 1 of results) & return & "Tracks:" & return\n'
            f'  repeat with t in results\n'
            f'    set output to output & (track number of t) & ". " & (name of t) & " (" & (round ((duration of t) / 60) rounding down) & ":" & text -2 thru -1 of ("0" & (round ((duration of t) mod 60))) & ")" & return\n'
            f'  end repeat\n'
            f'  return output\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find album '{query}' in your Apple Music library."
        return result

    elif action == "search" and safe_query:
        if app == "spotify":
            return "Spotify library search is not supported via AppleScript."
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (search playlist "Library" for "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set output to "Search results for \\"{safe_query}\\":" & return\n'
            f'  set maxItems to 15\n'
            f'  if (count of results) < maxItems then set maxItems to (count of results)\n'
            f'  repeat with i from 1 to maxItems\n'
            f'    set t to item i of results\n'
            f'    set output to output & "- " & (name of t) & " by " & (artist of t) & " (" & (album of t) & ")" & return\n'
            f'  end repeat\n'
            f'  if (count of results) > 15 then set output to output & "... and " & ((count of results) - 15) & " more results"\n'
            f'  return output\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"No results found for '{query}' in your Apple Music library."
        return result

    return f"Unknown action: {action}"


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
