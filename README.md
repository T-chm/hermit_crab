# Hermit Crab

A locally running, always-on voice assistant with a web interface. All processing happens on your machine — nothing is sent to the cloud.

- **Speech-to-text**: OpenAI Whisper
- **LLM**: Qwen 3.5 (4B) via Ollama
- **Interface**: Web UI served by FastAPI
- **Tools**: Music, weather, smart home, reminders, notes, summarize, messaging

## Requirements

- macOS (Apple Silicon recommended) or Linux
- Python 3.10+
- ffmpeg
- Ollama
- ~4 GB disk space for the LLM model
- ~1 GB for the Whisper base model (downloaded on first run)

## Quick Start

```bash
# 1. Install everything (auto-installs Homebrew, Python, ffmpeg, Ollama if needed)
./setup.sh

# 2. Run the app (starts Ollama automatically)
./run.sh

# 3. Open in browser
open http://localhost:8765
```

## Manual Installation

```bash
# Install ffmpeg (macOS)
brew install ffmpeg

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull the LLM model
ollama pull qwen3.5:4b

# Install Python dependencies
pip install -r requirements.txt
```

## Project Structure

```
hermit_crab/
  app.py              # FastAPI backend — WebSocket server, Whisper STT, Ollama streaming
  static/index.html   # Web UI — chat, audio capture, VAD, tool cards, quick actions
  tools/              # Plugin directory — drop a .py file here to add a tool
    __init__.py       # Auto-discovery loader
    _template.py      # Template for creating new tools
    music_control.py  # Apple Music / Spotify control
    weather.py        # Weather via wttr.in
    smart_home.py     # Philips Hue lights via openhue CLI
    reminders.py      # Apple Reminders via remindctl CLI
    notes.py          # Apple Notes via AppleScript
    summarize.py      # URL/PDF/YouTube summarization via summarize CLI
    messaging.py      # iMessage/SMS via imsg CLI
  whisper_ollama.py   # CLI version (standalone, no web UI)
  requirements.txt    # Python dependencies
  setup.sh            # One-step install script (creates .venv automatically)
  run.sh              # Start the app (activates venv and runs app.py)
```

## How It Works

1. The browser captures audio from your microphone via the Web Audio API
2. Audio is sent over a WebSocket to the FastAPI backend
3. The backend converts the audio to WAV (pydub/ffmpeg), then transcribes it with Whisper
4. The transcribed text is sent to Ollama's chat API with tool definitions
5. If the model invokes a tool (e.g. music control), the tool is executed and the result is fed back for a follow-up response
6. LLM response tokens stream back through the WebSocket and appear in the chat UI in real time

### Auto Think

Qwen 3.5 is a reasoning model that can perform chain-of-thought before answering. Hermit Crab uses a two-pass approach:

1. A fast classification call (~1s) asks the model whether the query needs deep reasoning
2. Simple queries (greetings, casual chat) get instant responses
3. Complex queries (math, code, analysis) automatically enable the thinking phase

Toggle "Auto think" on in the UI to enable this. It is off by default for maximum speed.

### Tool Calling

The LLM can call tools during a conversation. Tools are defined in the Ollama API request and the model decides when to use them based on the user's message. Tools are only invoked when the user explicitly asks for an action — the model will not call tools for greetings or general questions.

Each tool call produces a **rich UI card** in the chat with tool-specific styling, parsed results, and contextual action buttons.

Currently supported tools:

| Tool | What it does | Dependency |
|---|---|---|
| **Music** | Play, pause, skip, search, browse Apple Music / Spotify | None (Spotify needs [spogo](https://github.com/steipete/spogo)) |
| **Weather** | Current conditions and forecasts for any location | None (uses wttr.in) |
| **Smart Home** | Control Philips Hue lights, rooms, and scenes | [openhue CLI](https://github.com/openhue/openhue-cli) |
| **Reminders** | Create, view, and complete Apple Reminders | [remindctl](https://github.com/steipete/remindctl) |
| **Notes** | Create, search, and list Apple Notes | None (native AppleScript) |
| **Summarize** | Summarize web pages, PDFs, and YouTube videos | [summarize CLI](https://github.com/steipete/summarize) |
| **Messaging** | Send and read iMessages/SMS | [imsg CLI](https://github.com/steipete/imsg) |

### Quick Actions Bar

The UI includes a row of shortcut buttons above the text input for common operations:

- **Weather** — check local weather
- **Music controls** — previous, play/pause, next, now playing
- **Lights** — list smart home lights
- **Tasks** — show today's reminders
- **Notes** — list notes
- **Msgs** — show recent messages

These send pre-defined voice commands to the assistant, identical to typing them.

## Usage

### Two Listening Modes

**Push-to-talk** (default when "Always listen" is off):
- Click the mic button to start recording
- Click the mic button again to stop and send
- Works alongside text input

**Always-on** (toggle "Always listen"):
- Voice Activity Detection (VAD) monitors your microphone
- Recording starts automatically when speech is detected
- Sends automatically after 1.5 seconds of silence
- Adjust the sensitivity slider to tune for your environment

### Text Input

Type in the text box and press Enter or click Send. Works alongside voice input.

### Music Control

| Command | Example |
|---|---|
| Play/resume | "Play music" |
| Pause | "Pause the music" |
| Skip | "Next song" / "Previous track" |
| Play a song | "Play Bohemian Rhapsody" |
| Song by artist | "Play Volcano from U2" |
| Play an artist | "Play some Coldplay" (shuffles all their songs) |
| Play an album | "Play Abbey Road" |
| Now playing | "What song is playing?" |
| Search library | "Search my library for Beatles" |
| Browse | "Which artists do I have?" / "What albums do I have?" |

**Apple Music** works out of the box via AppleScript. **Spotify** requires [spogo](https://github.com/steipete/spogo) (`brew install steipete/tap/spogo && spogo auth import --browser chrome`). Without spogo, Spotify commands will prompt you to install it.

### Weather

No setup required. Uses [wttr.in](https://wttr.in) — no API key needed.

| Command | Example |
|---|---|
| Quick check | "What's the weather?" / "Weather in Tokyo" |
| Current detail | "Give me detailed weather for London" |
| Forecast | "What's the forecast for this week in Paris?" |

### Smart Home (Philips Hue)

Requires [openhue CLI](https://github.com/openhue/openhue-cli): `brew install openhue/cli/openhue-cli`. Press the button on your Hue Bridge on first run to pair.

| Command | Example |
|---|---|
| List lights | "Show me all the lights" |
| Turn on/off | "Turn off the bedroom light" / "Turn on the living room" |
| Brightness | "Set the desk lamp to 50%" |
| Color | "Make the bedroom light red" |
| Scenes | "Activate the relax scene in the bedroom" |

### Reminders

Requires [remindctl](https://github.com/steipete/remindctl): `brew install steipete/tap/remindctl`. Grant Reminders permission when prompted.

| Command | Example |
|---|---|
| View | "What are my reminders?" / "Show today's tasks" |
| Create | "Remind me to call mom tomorrow" |
| With due date | "Remind me to submit the report by Friday at 9am" |
| Complete | "Mark reminder 3 as done" |
| Lists | "Show my reminder lists" |

### Notes

No setup required — uses native macOS AppleScript.

| Command | Example |
|---|---|
| Create | "Take a note called Meeting Notes" |
| With body | "Make a note titled Groceries with milk, eggs, bread" |
| Search | "Find my note about recipes" |
| List | "List all my notes" / "Show notes in the Work folder" |

### Summarize

Requires [summarize CLI](https://github.com/steipete/summarize): `brew install steipete/tap/summarize`. Needs at least one API key (e.g. `GEMINI_API_KEY`).

| Command | Example |
|---|---|
| Web page | "Summarize https://example.com/article" |
| YouTube | "Summarize this video: https://youtu.be/..." |
| Short/long | "Give me a short summary of https://..." |

### Messaging (iMessage/SMS)

Requires [imsg CLI](https://github.com/steipete/imsg): `brew install steipete/tap/imsg`. Your terminal needs Full Disk Access (System Settings > Privacy > Full Disk Access).

| Command | Example |
|---|---|
| Send | "Text John I'm running late" |
| Read | "Show my recent messages" |
| Chat history | "Read my conversation with Mom" |

### Other Controls

- **Model selector**: Switch between installed Ollama models
- **Auto think**: Toggle automatic deep reasoning classification
- **Speak replies**: Enable browser text-to-speech for responses
- **Sensitivity slider**: Adjust VAD microphone threshold
- **Clear chat**: Reset conversation history

## Creating Tools

Tools are Python files in the `tools/` directory. Each file exports two things:

- `DEFINITION` — an Ollama tool calling schema (tells the LLM what the tool does)
- `execute(args)` — a function that runs the tool and returns a string

To create a new tool:

1. Copy `tools/_template.py` to `tools/your_tool.py`
2. Fill in the schema and implement `execute()`
3. Restart the server — it auto-discovers new tools

See `tools/weather.py` or `tools/notes.py` for real examples. A minimal tool looks like:

```python
import subprocess

DEFINITION = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "Does X. Only use when the user asks for X.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The input"},
            },
            "required": ["query"],
        },
    },
}

def execute(args: dict) -> str:
    query = args.get("query", "")
    r = subprocess.run(["some-cli", query], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() or "No result."
```

## Switching Models

Any model available in Ollama can be used. Pull a model and select it from the dropdown:

```bash
# Smaller/faster
ollama pull qwen2.5:3b

# Larger/smarter
ollama pull qwen2.5:14b

# Other families
ollama pull llama3.2
ollama pull qwen3:4b
```

The model dropdown in the UI includes common options. To add more, edit the `<select id="model-select">` element in `static/index.html`.

## Configuration

Edit the constants at the top of `app.py`:

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_LLM` | `qwen3.5:4b` | Ollama model name |
| `DEFAULT_WHISPER` | `base` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large` |
| `SYSTEM_PROMPT` | (see code) | LLM personality/instructions |
| `MAX_HISTORY` | `50` | Max conversation turns kept in memory |
| Port | `8765` | Change in `uvicorn.run()` at the bottom of `app.py` |

### Whisper Model Sizes

| Model | Size | Speed | Accuracy |
|---|---|---|---|
| `tiny` | 39 MB | Fastest | Basic |
| `base` | 74 MB | Fast | Good |
| `small` | 244 MB | Moderate | Better |
| `medium` | 769 MB | Slow | Great |
| `large` | 1550 MB | Slowest | Best |

## CLI Version

`whisper_ollama.py` is a standalone command-line version that doesn't require a browser:

```bash
# Record 5 seconds and send to LLM
python3 whisper_ollama.py

# Transcribe an audio file
python3 whisper_ollama.py -f audio.wav

# Continuous conversation mode
python3 whisper_ollama.py --loop

# Use a different model
python3 whisper_ollama.py -m qwen3.5:4b
```

## Troubleshooting

**"Cannot connect to Ollama"**
Ollama isn't running. `run.sh` starts it automatically, but you can also start it manually with `ollama serve`.

**No audio / microphone not working**
The browser needs microphone permission. Click the mic button and allow access when prompted. Only works on `localhost` or HTTPS.

**Whisper is slow**
Switch to a smaller model — edit `DEFAULT_WHISPER` in `app.py` to `tiny`. Or if you only need English, the `base.en` variant is faster.

**Model responses are slow**
Switch to a smaller LLM. `qwen2.5:3b` is roughly 2x faster than the 7B models. Select it from the dropdown or pull it with `ollama pull qwen2.5:3b`.

**VAD triggers on background noise**
Increase the sensitivity slider (higher = less sensitive). Move the threshold to the right until it stops triggering on ambient noise.

**Music control not working**
Make sure Apple Music or Spotify is open. On first use, macOS may prompt you to allow Terminal/Python to control the app — click Allow.

**Spotify says "spogo required"**
Install spogo: `brew install steipete/tap/spogo && spogo auth import --browser chrome`. Requires Spotify Premium.

**Tool says "CLI not installed"**
Each tool will tell you the exact install command if its CLI dependency is missing. All optional dependencies can be installed via Homebrew:

```bash
brew install steipete/tap/spogo        # Spotify
brew install openhue/cli/openhue-cli   # Philips Hue
brew install steipete/tap/remindctl    # Apple Reminders
brew install steipete/tap/summarize    # Summarize
brew install steipete/tap/imsg         # iMessage
```
