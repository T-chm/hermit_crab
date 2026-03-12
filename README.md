# 🦀 Hermit Crab

An AI voice assistant that controls your music, lights, messages, and more — running **entirely on your machine**. No cloud APIs for the brain, no mystery network calls, no API keys to get started.

> 🔒 **Private.** Whisper transcribes your voice locally. Ollama runs the LLM locally. Your conversations, commands, and data stay on your hardware. Zero outbound network calls by default.
>
> 🎙️ **Voice-first.** Built around speech from day one. Push-to-talk or always-on listening with real-time voice activity detection. Not a chatbot with a mic taped on.
>
> 🔍 **Transparent.** Single-file backend, single-file frontend. No framework magic, no hidden abstractions. Read the entire codebase and know exactly what runs when you say "turn off the lights."
>
> 🧩 **Hackable.** Drop a Python file in `tools/` and it just works. No config files, no manifests, no registration — auto-discovered on startup.

## 🚀 Get Started

```bash
./setup.sh          # installs everything
./run.sh            # starts the app
open http://localhost:8765
```

That's it. Talk or type.

## 🧰 What Can It Do?

Just ask naturally — Hermit Crab figures out the right tool.

| | Tool | Try saying... | Setup |
|---|---|---|---|
| ☀️ | **Daily Brief** | "Good morning" · "Daily brief" · "Catch me up" | Gmail/Calendar OAuth (see below) |
| 🎵 | **Music** | "Play some Coldplay" · "Next song" · "What's playing?" | Works with Apple Music. Spotify needs [spogo](https://github.com/steipete/spogo) |
| 🌤️ | **Weather** | "What's the weather in Tokyo?" | Nothing — just works |
| 📈 | **Stocks** | "How's Apple doing?" · "Market overview" · "TSLA" | Nothing — just works (uses yfinance) |
| ✉️ | **Gmail** | "Check my email" · "Search emails from John" | Gmail OAuth (see below) |
| 📅 | **Calendar** | "What's on my schedule?" · "Tomorrow's agenda" | Calendar OAuth (see below) |
| ✈️ | **Trips** | "Upcoming trips" · "Add trips to calendar" | Gmail + Calendar OAuth |
| 💡 | **Smart Home** | "Turn off the bedroom light" · "Set it to 50%" | `brew install openhue/cli/openhue-cli` |
| ✅ | **Reminders** | "Remind me to call mom tomorrow" | `brew install steipete/tap/remindctl` |
| 📝 | **Notes** | "Take a note called Meeting Notes" | Nothing — just works |
| 📄 | **Summarize** | "Summarize this article: https://..." | `brew install steipete/tap/summarize` + API key |
| 💬 | **Messaging** | "Text John I'm running late" | `brew install steipete/tap/imsg` + Full Disk Access |

Tools that need a CLI will tell you the exact install command if it's missing. The quick actions bar in the UI gives you one-tap shortcuts for the most common stuff.

### Daily Brief

Say "good morning" or "daily brief" and get a single dashboard card with:

- **Weather** for your location (auto-detected from IP, or reads your city from memory)
- **Stock watchlist** (reads your tickers from memory, or shows major indices)
- **Unread emails** (top 3 with total count)
- **Upcoming trips** (extracted from Gmail booking confirmations)
- **Music suggestion** (rotates by time of day — morning energy, afternoon focus, evening jazz, etc.) with a one-tap Play button

All four data sources are fetched in parallel (~5 seconds total).

### Trips Tool

The trips tool scans your Gmail for flight, hotel, Airbnb, car rental, train, and event bookings, then cross-references with your Google Calendar. It:

- Searches 10 travel-related Gmail query patterns (airlines, OTAs, booking confirmations)
- Uses Gmail batch API for performance (25+ emails fetched in a single HTTP request)
- Recursively walks MIME trees for deeply nested HTML emails (e.g., Trip.com)
- Extracts dates with context-awareness (check-in/check-out vs. cancellation deadlines)
- Handles ordinal dates ("24th July 2026")
- Filters noise (policy updates, marketing, surveys)
- Can create calendar events with 1-day and 1-week reminders

### Google OAuth Setup (Gmail, Calendar, Trips, Daily Brief)

These tools require Google OAuth credentials:

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the Gmail API and Google Calendar API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download `client_secret.json` to `~/.config/gws/client_secret.json`
5. On first use, a browser window opens for consent. The token is cached at `~/.hermit_crab/google_token.json`

## 🧠 Smart Features

### Tiered Memory

Hermit Crab remembers you across sessions:

- **Working memory** — in-session compaction keeps context manageable
- **Session memory** — per-session summaries saved to `~/.hermit_crab/sessions/`
- **Core facts** — LLM-extracted user facts saved to `~/.hermit_crab/memory.json` (location, preferences, watchlist, etc.)

The Daily Brief reads from core facts to personalize weather location and stock watchlist.

### Adaptive Thinking

When deep thinking mode is enabled, the LLM dynamically allocates a thinking budget based on query complexity:

| Complexity | Budget | Examples |
|---|---|---|
| **None** | Off | Greetings, tool calls, simple facts |
| **Light** | ~2K tokens | Explanations, comparisons, opinions |
| **Deep** | ~8K tokens | Multi-step math, coding, debugging |

A fast classifier call decides the tier before each response — no wasted thinking on simple requests.

### Agent Mode

Toggle agent mode for autonomous multi-step tasks. The agent plans, acts, evaluates, and iterates — useful for research or complex workflows that need multiple tool calls.

### Rich UI Cards

Tools with structured data (stocks, gmail, calendar, trips, daily brief) render as rich interactive cards — no redundant text summary underneath. Other tools (weather, music, reminders) still get an LLM-composed follow-up.

### Direct Dispatch

Common requests bypass the LLM entirely for instant response (~0s vs ~3.5s). Regex patterns match phrases like "pause the music", "what's the weather in London", "daily brief", "upcoming trips", etc. and dispatch directly to the right tool.

## 🎤 Two Ways to Talk

**Push-to-talk** (default) — Click mic → speak → click mic to send

**Always-on** — Toggle "Always listen" and it auto-detects when you're talking. Adjust the sensitivity slider to ignore background noise.

Or just type. Whatever works.

## ⚙️ Configuration

Edit the top of `app.py`:

| Setting | Default | What it does |
|---|---|---|
| `DEFAULT_LLM` | `qwen3.5:4b` | Which Ollama model to use |
| `DEFAULT_WHISPER` | `base` | Whisper size: `tiny` (fast) → `large` (accurate) |
| `MAX_HISTORY` | `50` | Conversation memory length |

Switch models on the fly from the dropdown in the UI, or pull new ones:

```bash
ollama pull qwen2.5:3b    # smaller/faster
ollama pull qwen2.5:14b   # bigger/smarter
```

## 🔌 Add Your Own Tools

Drop a Python file in `tools/` and restart. It's auto-discovered.

```bash
cp tools/_template.py tools/my_tool.py
# edit it, restart, done
```

Each tool just needs a `DEFINITION` dict (tells the LLM when to use it) and an `execute()` function (does the thing). See `tools/weather.py` for a clean example.

## 🖥️ CLI Mode

Don't want the web UI? There's a terminal version:

```bash
python3 whisper_ollama.py          # one-shot
python3 whisper_ollama.py --loop   # continuous conversation
```

## 🐛 Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot connect to Ollama" | Run `ollama serve` or just use `./run.sh` (starts it automatically) |
| No audio / mic not working | Allow mic access in browser. Only works on `localhost` or HTTPS |
| Slow responses | Use a smaller model — `qwen2.5:3b` is ~2x faster |
| Slow transcription | Set `DEFAULT_WHISPER = "tiny"` in `app.py` |
| VAD triggers on noise | Slide the sensitivity slider to the right |
| Music not working | Make sure Apple Music or Spotify is actually open |
| "CLI not installed" | The error message tells you the exact `brew install` command to run |
| Google auth error | Delete `~/.hermit_crab/google_token.json` and retry to re-authenticate |
