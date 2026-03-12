# 🦀 Hermit Crab

A local-first AI assistant with extensible tools, adaptive reasoning, and full privacy control. Runs entirely on your machine — your data never leaves.

## Get Started

```bash
./setup.sh          # installs Ollama, Python deps, Whisper model
./run.sh            # starts Ollama + web server
open http://localhost:8765
```

For Gmail, Calendar, and Trips you'll need Google OAuth — see [SETUP.md](SETUP.md) for a 5-minute walkthrough. Everything else works immediately.

## Why Hermit Crab?

**Your conversations shouldn't live on someone else's server.** Cloud assistants route every query through remote APIs — your voice, your questions, your habits, all logged and stored on infrastructure you don't control. Hermit Crab runs the LLM (Ollama) and speech recognition (Whisper) entirely on your machine. No cloud APIs, no API keys, no accounts. Nothing leaves unless a tool explicitly needs to reach out.

**AI assistants shouldn't be black boxes.** Most assistants make network calls you can't see, collect telemetry you can't disable, and change behavior through silent updates. Hermit Crab is a single-file backend and a single-file frontend. The LLM and speech processing are fully offline. Tools that do reach out (weather, stocks, Gmail) use standard APIs you can read and audit — no hidden calls, no telemetry, no surprises.

**You shouldn't need permission to extend your own assistant.** Alexa has Skills certification. Siri has no plugin story. Most local LLM UIs have no tool system at all. In Hermit Crab, you drop a Python file in `tools/` and restart — auto-discovered, no config, no approval process. It ships with 12 tools out of the box and you can add more in minutes.

**Local LLMs shouldn't waste time thinking about simple questions.** Most setups either always run in "thinking mode" (slow for everything) or never do (misses nuance). Hermit Crab uses a fast classifier to size up each query and dynamically allocate a thinking budget — instant answers for "play some jazz", deep reasoning for "debug this function".

## Tools

| | Tool | Examples |
|---|---|---|
| ☀️ | **Daily Brief** | "Good morning" · "Catch me up" |
| 📈 | **Stocks** | "How's Apple doing?" · "TSLA" · "Market overview" |
| ✉️ | **Gmail** | "Check my email" · "Search emails from John" |
| 📅 | **Calendar** | "What's on my schedule?" · "Tomorrow's agenda" |
| ✈️ | **Trips** | "Upcoming trips" · "Add trips to calendar" |
| 🎵 | **Music** | "Play some Coldplay" · "Next song" |
| 🌤️ | **Weather** | "Weather in Tokyo" |
| 💡 | **Smart Home** | "Turn off the bedroom light" |
| ✅ | **Reminders** | "Remind me to call mom tomorrow" |
| 📝 | **Notes** | "Take a note called Meeting Notes" |
| 📄 | **Summarize** | "Summarize this article: https://..." |
| 💬 | **Messaging** | "Text John I'm running late" |

The Daily Brief pulls weather, your stock watchlist, unread emails, and upcoming trips into a single card — all fetched in parallel. It reads your location and watchlist from memory so it's personalized from day one.

## How It Works

**Direct dispatch** — Common requests (tool calls, music controls, daily brief) bypass the LLM and go straight to the tool. Instant response, zero latency.

**Adaptive thinking** — When thinking mode is on, a lightweight classifier decides the budget per query:

| Query type | Budget |
|---|---|
| Commands, facts, greetings | No thinking |
| Explanations, comparisons | ~2K tokens |
| Math, coding, debugging | ~8K tokens |

**Memory** — Hermit Crab learns your preferences across sessions. Core facts (location, music taste, stock watchlist) are extracted and persisted at `~/.hermit_crab/memory.json`. Tools like Daily Brief use these to personalize results without you having to repeat yourself.

**Agent mode** — For multi-step tasks, toggle agent mode. It plans, executes tools, evaluates results, and iterates autonomously.

**Rich UI** — Tools with structured data render as interactive cards (stock charts, email lists, trip timelines, calendar views). No redundant text summary underneath.

## Add Your Own Tools

```bash
cp tools/_template.py tools/my_tool.py
# edit it, restart, done
```

Each tool exports a `DEFINITION` dict and an `execute()` function. That's it. See `tools/weather.py` for a minimal example. Hermit Crab auto-discovers tools on startup — no registration, no config files.

## Interface

Type or talk — both work. The web UI supports push-to-talk and always-on voice with adjustable sensitivity. There's also a CLI mode (`python3 whisper_ollama.py --loop`).

## Docs

See [SETUP.md](SETUP.md) for detailed setup instructions, Google OAuth configuration, CLI tool dependencies, model selection, and troubleshooting.
