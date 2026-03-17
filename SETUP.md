# Setup & Configuration

## Quick Start

```bash
./setup.sh          # installs Ollama, Python deps, Whisper
./run.sh            # starts Ollama + the app
open http://localhost:8765
```

## Configuration

Edit the top of `app.py`:

| Setting | Default | What it does |
|---|---|---|
| `DEFAULT_LLM` | `qwen3.5:4b` | Ollama model to use |
| `DEFAULT_WHISPER` | `base` | Whisper size: `tiny` (fast) to `large` (accurate) |
| `MAX_HISTORY` | `50` | Conversation memory length |

You can switch models from the UI dropdown or pull new ones:

```bash
ollama pull qwen3.5:4b    # default, fast
ollama pull qwen3.5:9b    # larger, better at extraction
```

For client memory ingestion (extracting preferences from conversations), the 9b model produces noticeably better results than 4b.

## WeChat Data Export

The primary data source for client profiles is WeChat conversation history, exported via [wechat-decrypt](https://github.com/nicholaschenai/wechat-decrypt).

### Prerequisites

- macOS with WeChat 4.x installed
- Python 3.10+
- Xcode Command Line Tools

### Export Steps

```bash
cd ~/Downloads/wechat-decrypt
pip install -r requirements.txt

# Build the memory scanner
mkdir -p build
cc -O2 -o build/find_all_keys_macos csrc/find_all_keys_macos.c -framework Foundation

# Run the full export pipeline
./run.sh
```

This produces:
- `exported/wechat_contacts.json` -- contact list
- `exported/chats/<name>.json` -- per-conversation message history

### Ingesting into Hermit Crab

Once exported, open Hermit Crab and type:

```
ingest wechat conversations
```

Or to ingest a specific client:

```
ingest wechat conversations for Zhang Wei
```

Client profiles are saved to `~/.hermit_crab/clients/`. Re-run ingestion anytime to pick up new messages. Existing profiles are updated incrementally.

### Custom Export Path

By default, the tool reads from `test_data/wechat_export/` (included sample data for development). For production use with real WeChat data, pass the `wechat_dir` parameter or update `_DEFAULT_WECHAT_DIR` in `tools/client_memory.py` to point to `~/Downloads/wechat-decrypt/exported/`.

### Alternative: Text File Ingestion

Drop `.txt` or `.csv` conversation transcripts into `~/.hermit_crab/inbox/`, then:

```
ingest conversations from inbox
```

File names are used as client names (e.g., `john_doe_sms.txt` becomes "John Doe Sms").

## Google OAuth (Gmail, Calendar)

These tools access your Google account and require OAuth credentials.

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the **Gmail API** and **Google Calendar API**
3. Create **OAuth 2.0 credentials** (Desktop app type)
4. Download `client_secret.json` to `~/.config/gws/client_secret.json`
5. On first use, a browser window opens for consent
6. The token is cached at `~/.hermit_crab/google_token.json`

To re-authenticate, delete the token file and retry.

## Tool Dependencies

Most tools work out of the box. Some require external CLIs:

| Tool | Dependency | Install |
|---|---|---|
| Reminders | [remindctl](https://github.com/steipete/remindctl) | `brew install steipete/tap/remindctl` |

Tools will tell you the exact install command if a dependency is missing.

## Voice Input

**Push-to-talk** (default). Click mic, speak, click mic to send.

**Always-on**. Toggle "Always listen" in the UI. Adjust the sensitivity slider to ignore background noise.

Ideal for hands-free use in the car before a showing: "Prep me for my meeting with Zhang Wei at 456 Maple Drive."

## Data & Privacy

All data is stored locally:

| Data | Location |
|---|---|
| Client profiles | `~/.hermit_crab/clients/*.json` |
| Google OAuth token | `~/.hermit_crab/google_token.json` |
| Core memory (facts) | `~/.hermit_crab/memory.json` |
| Session summaries | `~/.hermit_crab/sessions/` |
| Text transcript inbox | `~/.hermit_crab/inbox/` |

All LLM inference runs locally via Ollama. Client conversations are never sent to any cloud service. The only outbound network calls are:

- **Weather**: Open-Meteo API (free, no API key, no tracking)
- **Gmail/Calendar**: Google API (only if OAuth is configured)

To reset everything: `rm -rf ~/.hermit_crab`

## Directory Structure

```
hermit_crab/
  app.py                    # Backend: FastAPI, WebSocket, Ollama, Whisper
  static/index.html         # Frontend: single-file UI with Tailwind CSS
  tools/
    client_brief.py         # Hero tool: pre-meeting briefing card
    client_memory.py        # WeChat/text ingestion, client profile management
    weather.py              # Open-Meteo weather
    calendar.py             # Google Calendar integration
    gmail.py                # Gmail integration
    notes.py                # Apple Notes
    reminders.py            # Apple Reminders
    _template.py            # Template for new tools
    _google_auth.py         # Shared Google OAuth helper
  test_data/
    wechat_export/          # Simulated WeChat data for development
      wechat_contacts.json
      chats/*.json
```

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot connect to Ollama" | Run `ollama serve` or use `./run.sh` |
| No audio or mic not working | Allow mic access in browser. Only works on `localhost` or HTTPS |
| Slow responses | Use a smaller model: `qwen3.5:4b` |
| Slow transcription | Set `DEFAULT_WHISPER = "tiny"` in `app.py` |
| VAD triggers on noise | Increase the sensitivity slider |
| Google auth error | Delete `~/.hermit_crab/google_token.json` and retry |
| "WeChat export not found" | Run `wechat-decrypt/run.sh` first, or use test data |
| Poor extraction quality | Use `qwen3.5:9b` or larger model for ingestion |
| "No profile found" | Run "ingest wechat conversations" before querying clients |
