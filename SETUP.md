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
| `DEFAULT_WHISPER` | `base` | Whisper size: `tiny` (fast) → `large` (accurate) |
| `MAX_HISTORY` | `50` | Conversation memory length |

Switch models from the UI dropdown, or pull new ones:

```bash
ollama pull qwen2.5:3b    # smaller/faster
ollama pull qwen2.5:14b   # bigger/smarter
```

## Google OAuth (Gmail, Calendar, Trips, Daily Brief)

These tools access your Google account and require OAuth credentials:

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the **Gmail API** and **Google Calendar API**
3. Create **OAuth 2.0 credentials** (Desktop app type)
4. Download `client_secret.json` to `~/.config/gws/client_secret.json`
5. On first use, a browser window opens for consent
6. Token is cached at `~/.hermit_crab/google_token.json`

To re-authenticate, delete the token file and retry.

## Tool Dependencies

Most tools work out of the box. Some require external CLIs:

| Tool | Dependency | Install |
|---|---|---|
| Music (Spotify) | [spogo](https://github.com/steipete/spogo) | `brew install steipete/tap/spogo && spogo auth import --browser chrome` |
| Smart Home | [openhue-cli](https://github.com/openhue/openhue-cli) | `brew install openhue/cli/openhue-cli` |
| Reminders | [remindctl](https://github.com/steipete/remindctl) | `brew install steipete/tap/remindctl` |
| Summarize | [summarize](https://github.com/steipete/summarize) | `brew install steipete/tap/summarize` + API key |
| Messaging | [imsg](https://github.com/steipete/imsg) | `brew install steipete/tap/imsg` + Full Disk Access |
| Stocks | yfinance | `pip install yfinance` (included in setup) |

Tools will tell you the exact install command if a dependency is missing.

Apple Music works natively via AppleScript — no setup needed.

## Voice Input

**Push-to-talk** (default) — Click mic → speak → click mic to send.

**Always-on** — Toggle "Always listen" in the UI. Adjust the sensitivity slider to ignore background noise.

## CLI Mode

```bash
python3 whisper_ollama.py          # one-shot
python3 whisper_ollama.py --loop   # continuous conversation
```

## Data & Privacy

All data is stored locally:

| Data | Location |
|---|---|
| Google OAuth token | `~/.hermit_crab/google_token.json` |
| Core memory (facts) | `~/.hermit_crab/memory.json` |
| Session summaries | `~/.hermit_crab/sessions/` |
| Notes | `~/.hermit_crab/notes/` |

To reset everything: `rm -rf ~/.hermit_crab`

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot connect to Ollama" | Run `ollama serve` or use `./run.sh` |
| No audio / mic not working | Allow mic access in browser. Only works on `localhost` or HTTPS |
| Slow responses | Use a smaller model: `qwen2.5:3b` |
| Slow transcription | Set `DEFAULT_WHISPER = "tiny"` in `app.py` |
| VAD triggers on noise | Increase the sensitivity slider |
| Music not working | Make sure Apple Music or Spotify is open |
| Google auth error | Delete `~/.hermit_crab/google_token.json` and retry |
| "CLI not installed" | The error message shows the exact `brew install` command |
