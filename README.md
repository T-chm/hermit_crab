# 🦀 Hermit Crab

![Hermit Crab Features](features.png)

A local-first AI assistant with extensible tools, adaptive reasoning, and full privacy control. Runs entirely on your machine. Your data never leaves.

## Why Hermit Crab?

- **100% Private:** No cloud APIs. No telemetry. Your voice, questions, and habits stay on your machine.
- **Transparent:** Single-file backend and frontend. The tools use standard, auditable APIs so there are no hidden network calls.
- **Infinitely Extensible:** Just drop a Python file in `tools/` and restart. No complex config or approval process.
- **Adaptive Thinking:** Simple queries get instant answers. Complex tasks get deep reasoning models. Fast and smart where it matters.

## Get Started

```bash
./setup.sh          # installs Ollama, Python deps, Whisper model
./run.sh            # starts Ollama + web server
open http://localhost:8765
```

Gmail, Calendar, and Trips need Google OAuth. See [SETUP.md](SETUP.md) for a 5-minute walkthrough. Everything else works immediately.

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

The Daily Brief pulls weather, your stock watchlist, unread emails, and upcoming trips into a single card. All fetched in parallel. It reads your location and watchlist from memory so it's personalized from day one.

## How It Works

**Direct dispatch.** Common requests bypass the LLM and go straight to the tool. Instant response, zero latency.

**Adaptive thinking.** When thinking mode is on, a lightweight classifier decides the budget per query:

| Query type | Budget |
|---|---|
| Commands, facts, greetings | No thinking |
| Explanations, comparisons | ~2K tokens |
| Math, coding, debugging | ~8K tokens |

**Memory.** Hermit Crab learns your preferences across sessions. Core facts like location, music taste, and stock watchlist are extracted and persisted. Tools like Daily Brief use these to personalize results without you repeating yourself.

**Agent mode.** For multi-step tasks, toggle agent mode. It plans, executes tools, evaluates results, and iterates autonomously.

**Rich UI.** Tools with structured data render as interactive cards: stock charts, email lists, trip timelines, calendar views. No redundant text summary underneath.

## Add Your Own Tools

```bash
cp tools/_template.py tools/my_tool.py
# edit it, restart, done
```

Each tool exports a `DEFINITION` dict and an `execute()` function. That's it. See `tools/weather.py` for a minimal example. Hermit Crab auto-discovers tools on startup. No registration, no config files.

## Interface

Type or talk. The web UI supports push-to-talk and always-on voice with adjustable sensitivity. There's also a CLI mode (`python3 whisper_ollama.py --loop`).

## Docs

See [SETUP.md](SETUP.md) for detailed setup, Google OAuth configuration, CLI tool dependencies, model selection, and troubleshooting.
