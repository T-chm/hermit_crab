# 🦀 Hermit Crab

**A local-first, voice-native alternative to [OpenClaw](https://github.com/AiCEG/openclaw).**

Same idea — an AI assistant that controls your music, lights, messages, and more. But Hermit Crab runs entirely on your machine. No cloud APIs for the brain, no mystery network calls, no API keys for the core experience.

> **🔒 Local by default.** Whisper transcribes your voice locally. Ollama runs the LLM locally. Your conversations, commands, and data never leave your machine.
>
> **🎙️ Voice-native.** Built around speech from day one — not bolted on. Push-to-talk or always-on with voice activity detection.
>
> **🔍 Transparent.** ~400 lines of Python. No framework magic, no hidden abstractions. You can read the entire codebase in 15 minutes and understand exactly what happens when you say "turn off the lights."

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
| 🎵 | **Music** | "Play some Coldplay" · "Next song" · "What's playing?" | Works with Apple Music. Spotify needs [spogo](https://github.com/steipete/spogo) |
| 🌤️ | **Weather** | "What's the weather in Tokyo?" | Nothing — just works |
| 💡 | **Smart Home** | "Turn off the bedroom light" · "Set it to 50%" | `brew install openhue/cli/openhue-cli` |
| ✅ | **Reminders** | "Remind me to call mom tomorrow" | `brew install steipete/tap/remindctl` |
| 📝 | **Notes** | "Take a note called Meeting Notes" | Nothing — just works |
| 📄 | **Summarize** | "Summarize this article: https://..." | `brew install steipete/tap/summarize` + API key |
| 💬 | **Messaging** | "Text John I'm running late" | `brew install steipete/tap/imsg` + Full Disk Access |

Tools that need a CLI will tell you the exact install command if it's missing. The quick actions bar in the UI gives you one-tap shortcuts for the most common stuff.

## 🦀 vs 🦞 How is this different from OpenClaw?

| | Hermit Crab | OpenClaw |
|---|---|---|
| **LLM** | Runs locally via Ollama — no API key, no cloud | Cloud LLMs (OpenAI, Anthropic, etc.) |
| **Voice** | Built-in Whisper STT + always-on VAD | Add-on via skills |
| **Privacy** | Everything on your machine | Conversations go through cloud APIs |
| **Networking** | `localhost` only — zero outbound by default | Requires internet for LLM |
| **Skills/Tools** | Python files in `tools/`, auto-discovered | SKILL.md + scripts directories |
| **Setup** | `./setup.sh && ./run.sh` | Requires Claude Code / Codex CLI |
| **Codebase** | ~400 lines, single file backend | Larger framework with skill marketplace |

Hermit Crab shares many of the same tool ideas (and CLI dependencies) as OpenClaw, but wraps them in a simpler, local-first, voice-first package. If you want cloud-powered intelligence with a huge skill ecosystem, use OpenClaw. If you want something private, hackable, and self-contained, try the crab. 🦀

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
