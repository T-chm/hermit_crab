# Hermit Crab Real Estate Edition

A local-first AI assistant purpose-built for real estate agents. Eliminates the 30+ minute meeting prep by generating instant client briefings from WeChat conversation history and live property data. Runs entirely on your machine. Client data never leaves.

## The Problem

Real estate agents juggle dozens of active clients across scattered communications (WeChat, email, texts, CRM notes). Before every meeting, they spend 30+ minutes manually piecing together: What did we last discuss? What's their budget now? Which properties did they reject, and why? What personal details should I remember?

## The Solution

Say **"Prep me for my meeting with Zhang Wei at 456 Maple Drive"** and get an instant briefing card with:

- **Recent Discussions** -- what you talked about last, summarized from WeChat history
- **Current Preferences** -- budget, locations, must-haves, dealbreakers (auto-updated as conversations evolve)
- **Property History** -- every property shown, liked, or rejected with reasons
- **Personal Notes** -- family details, hobbies, job changes, conversation icebreakers
- **Property Alignment** -- how today's property matches the client's stated preferences

All extracted locally from your WeChat conversations by a local LLM. No cloud APIs. No data leaving your machine.

## Get Started

```bash
# 1. Install dependencies
./setup.sh

# 2. Export WeChat conversations (requires wechat-decrypt)
cd ~/Downloads/wechat-decrypt && ./run.sh

# 3. Start Hermit Crab
./run.sh
open http://localhost:8765

# 4. Ingest your client conversations
# In the UI, type: "ingest wechat conversations"
```

Gmail and Calendar need Google OAuth. See [SETUP.md](SETUP.md) for a 5-minute walkthrough.

## Tools

| | Tool | Examples |
|---|---|---|
| 📋 | **Client Brief** | "Prep me for my meeting with Zhang Wei" · "Brief me on David Chen at 456 Maple Drive" |
| 👤 | **Client Memory** | "Ingest wechat conversations" · "List my clients" · "Show Zhang Wei's preferences" |
| ⛅ | **Weather** | "Weather in Tokyo" · "Forecast for the weekend" |
| 📅 | **Calendar** | "What showings do I have today?" · "Tomorrow's schedule" |
| ✉️ | **Gmail** | "Check my email" · "Search emails from Zhang Wei" |
| ✅ | **Reminders** | "Remind me to follow up with David Chen tomorrow" |
| 📝 | **Notes** | "Take a note about the Oak Lane showing" |

## How It Works

### Client Memory Pipeline

1. **WeChat Export** -- uses [wechat-decrypt](https://github.com/nicholaschenai/wechat-decrypt) to export your WeChat conversations as JSON
2. **LLM Extraction** -- local Ollama model reads each conversation and extracts 4 vectors: recent topics, preferences, property history, and personal details
3. **Incremental Updates** -- re-run ingestion anytime. New messages merge into existing profiles without overwriting
4. **Per-Client Profiles** -- stored as JSON in `~/.hermit_crab/clients/`. Fully portable, human-readable, editable

### Instant Client Brief

When you say "prep me for my meeting with [Client]":

1. Fuzzy-matches the client name against stored profiles
2. Loads their 4-vector profile
3. (Optional) Fetches live property data if an address is provided
4. LLM synthesizes conversational summaries for each section
5. Renders a rich UI card with all the context you need

### Architecture

- **Backend**: `app.py` -- FastAPI + WebSocket, Ollama LLM, Whisper STT
- **Frontend**: `static/index.html` -- single HTML file with Tailwind CSS
- **Tools**: auto-discovered plugins in `tools/`. Drop a Python file, restart, done
- **Data**: `~/.hermit_crab/clients/` for client profiles, `~/.hermit_crab/inbox/` for text transcripts

### Direct Dispatch

Common requests bypass the LLM entirely for instant response:

| Pattern | Tool |
|---|---|
| "Prep me for my meeting with [Client]" | Client Brief |
| "Brief me on [Client]" | Client Brief |
| "Ingest wechat conversations" | Client Memory |
| "List my clients" | Client Memory |
| "[Client]'s preferences" | Client Memory |
| "Weather in [Location]" | Weather |
| "Remind me to [Task]" | Reminders |

### Model Switching

Switch between any locally installed Ollama model from the UI dropdown. Models are dynamically fetched on connect. The previous model is unloaded to free VRAM before loading the new one.

### Adaptive Thinking

When thinking mode is on, a lightweight classifier decides the reasoning budget:

| Query type | Budget |
|---|---|
| Commands, tool calls, greetings | No thinking |
| Explanations, comparisons | ~2K tokens |
| Complex analysis, debugging | ~16K tokens |

## Client Profile Schema

Each client profile at `~/.hermit_crab/clients/{name}.json`:

```json
{
  "name": "Zhang Wei & Li Na",
  "source": "wechat",
  "vectors": {
    "recent_topics": [
      {"date": "2026-03-08", "summary": "Expanded budget to $900k, finished basement now mandatory"}
    ],
    "preferences": {
      "budget_min": 700000,
      "budget_max": 900000,
      "locations": ["Maple Heights"],
      "must_haves": ["finished basement", "fenced yard", "home office"],
      "dealbreakers": ["traffic noise", "no basement"]
    },
    "property_history": [
      {"address": "123 Oak Lane", "status": "rejected", "notes": "Backyard too small for dogs"},
      {"address": "789 Elm St", "status": "rejected", "notes": "Traffic noise, can't work from home"}
    ],
    "particularities": [
      "Two dogs, need fenced yard",
      "Li Na works from home, needs quiet",
      "Son plays soccer, ask about tournament"
    ]
  }
}
```

## Data Ingestion Sources

| Source | Method |
|---|---|
| **WeChat** (primary) | Export via wechat-decrypt, then "ingest wechat" in UI |
| **Text files** | Drop `.txt` or `.csv` files in `~/.hermit_crab/inbox/`, then "ingest conversations" |
| **Manual** | "Update David Chen's profile: he just got a dog" |

## Privacy

- All LLM inference runs locally via Ollama. No API keys, no cloud calls
- Client conversations are processed on your machine and stored locally
- WeChat decryption happens entirely offline
- The only network calls are weather (Open-Meteo, free, no API key) and optional Google OAuth for Gmail/Calendar

## Add Your Own Tools

```bash
cp tools/_template.py tools/my_tool.py
# edit DEFINITION and execute(), restart, done
```

Each tool exports a `DEFINITION` dict (Ollama schema) and an `execute(args) -> str` function. Auto-discovered on startup.

## Docs

See [SETUP.md](SETUP.md) for detailed setup, WeChat export configuration, Google OAuth, model selection, and troubleshooting.
