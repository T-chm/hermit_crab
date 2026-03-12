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

**Fully local.** LLM runs via Ollama, speech-to-text via Whisper — no cloud APIs, no API keys, no accounts. Everything stays on your hardware.

**Extensible tools.** Drop a Python file in `tools/` and restart. Auto-discovered, no config. Hermit Crab ships with 12 tools out of the box — music, email, calendar, stocks, smart home, and more.

**Transparent networking.** You control what goes over the network. The LLM and speech processing are fully offline. Tools that reach out (weather, stocks, Gmail) do so with standard APIs you can inspect — no telemetry, no hidden calls.

**Adaptive thinking.** A fast classifier sizes up each query and allocates a thinking budget accordingly — quick answers for simple requests, deep reasoning only when it's needed.

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
