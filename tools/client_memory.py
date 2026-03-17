"""Client Memory — ingest communications and manage per-client profiles."""

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DEFINITION = {
    "type": "function",
    "function": {
        "name": "client_memory",
        "description": (
            "Manage real estate client profiles. Ingest WeChat conversations or "
            "text transcripts to build client profiles with preferences, property "
            "history, and personal details. Query or list client information. "
            "Use when the user mentions clients, ingesting conversations, or "
            "looking up client preferences and history."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "ingest_wechat", "ingest_folder",
                        "query", "list_clients", "update", "delete",
                    ],
                    "description": (
                        "ingest_wechat: process WeChat exports into client profiles. "
                        "ingest_folder: process text/csv files from inbox folder. "
                        "query: look up a client's profile. "
                        "list_clients: show all known clients. "
                        "update: manually add info to a client. "
                        "delete: remove a client profile."
                    ),
                },
                "client_name": {
                    "type": "string",
                    "description": "Client name for query/update/delete. Optional for ingest (processes only matching chat).",
                },
                "info": {
                    "type": "string",
                    "description": "Free-text information to add (for update action).",
                },
                "wechat_dir": {
                    "type": "string",
                    "description": "Override path to wechat-decrypt exported directory.",
                },
            },
            "required": ["action"],
        },
    },
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CLIENTS_DIR = Path.home() / ".hermit_crab" / "clients"
INBOX_DIR = Path.home() / ".hermit_crab" / "inbox"
# Default: test data for development; override with wechat_dir param for production
_DEFAULT_WECHAT_DIR = Path(__file__).parent.parent / "test_data" / "wechat_export"

CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
INBOX_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = "http://localhost:11434"

# ---------------------------------------------------------------------------
# LLM extraction prompt
# ---------------------------------------------------------------------------
EXTRACT_PROMPT = """\
You are analyzing communications between a real estate agent and their client(s).
Extract structured information into these 4 vectors. Use the EXACT JSON format below.

Messages may be in Chinese, English, or a mix. Extract information regardless of language.
Translate Chinese content to English in the output.

Return ONLY valid JSON, no explanation:
{
  "recent_topics": [
    {"date": "YYYY-MM-DD", "summary": "brief description of what was discussed"}
  ],
  "preferences": {
    "budget_min": null or number,
    "budget_max": null or number,
    "locations": ["preferred areas"],
    "must_haves": ["required features"],
    "dealbreakers": ["things to avoid"],
    "style": "preferred style or empty string"
  },
  "property_history": [
    {"address": "...", "status": "shown|liked|rejected", "date": "YYYY-MM-DD", "notes": "reaction/reason"}
  ],
  "particularities": ["personal details worth remembering"]
}

If a field has no data, use null, empty array [], or empty string as appropriate.
"""


def _llm_extract(text: str) -> dict:
    """Call local Ollama to extract client vectors from a conversation chunk."""
    payload = json.dumps({
        "model": "qwen3.5:4b",
        "messages": [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "think": False,
        "keep_alive": "10m",
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    content = result.get("message", {}).get("content", "")
    # Try to extract JSON from the response (model may wrap in markdown)
    m = re.search(r"\{[\s\S]*\}", content)
    if m:
        return json.loads(m.group(0))
    return {}


# ---------------------------------------------------------------------------
# Client profile I/O
# ---------------------------------------------------------------------------
def _normalize_name(name: str) -> str:
    """Normalize client name to a safe filename."""
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_').lower()


def _load_client(name: str) -> dict | None:
    """Load a client profile by exact normalized name."""
    path = CLIENTS_DIR / f"{_normalize_name(name)}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _find_client(name: str) -> dict | None:
    """Fuzzy-find a client profile by name."""
    target = name.lower().strip()
    best = None
    for f in CLIENTS_DIR.glob("*.json"):
        profile = json.loads(f.read_text())
        pname = profile.get("name", "").lower()
        if target in pname or pname in target:
            best = profile
            break
        # Also check words overlap
        target_words = set(target.split())
        pname_words = set(pname.split())
        if target_words & pname_words:
            best = profile
    return best


def _save_client(profile: dict):
    """Save a client profile to disk."""
    path = CLIENTS_DIR / f"{_normalize_name(profile['name'])}.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2))


def _empty_profile(name: str, source: str = "unknown") -> dict:
    return {
        "name": name,
        "created": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
        "source": source,
        "vectors": {
            "recent_topics": [],
            "preferences": {
                "budget_min": None, "budget_max": None,
                "locations": [], "must_haves": [],
                "dealbreakers": [], "style": "",
            },
            "property_history": [],
            "particularities": [],
        },
        "raw_sources": [],
    }


def _merge_vectors(existing: dict, extracted: dict):
    """Merge extracted vectors into existing profile vectors."""
    v = existing.get("vectors", {})

    # Recent topics: append new, keep last 20
    new_topics = extracted.get("recent_topics") or []
    v.setdefault("recent_topics", []).extend(new_topics)
    v["recent_topics"] = v["recent_topics"][-20:]

    # Preferences: merge (newer overwrites)
    new_prefs = extracted.get("preferences") or {}
    prefs = v.setdefault("preferences", {})
    for key in ("budget_min", "budget_max", "style"):
        val = new_prefs.get(key)
        if val is not None and val != "":
            prefs[key] = val
    for key in ("locations", "must_haves", "dealbreakers"):
        new_items = new_prefs.get(key) or []
        existing_items = prefs.get(key, [])
        merged = list(dict.fromkeys(existing_items + new_items))  # dedup, preserve order
        prefs[key] = merged

    # Property history: merge by address
    new_props = extracted.get("property_history") or []
    existing_props = {p["address"].lower(): p for p in v.get("property_history", [])}
    for p in new_props:
        addr = (p.get("address") or "").lower()
        if addr:
            existing_props[addr] = p  # newer overwrites
    v["property_history"] = list(existing_props.values())

    # Particularities: append, dedup
    new_parts = extracted.get("particularities") or []
    existing_parts = v.get("particularities", [])
    merged = list(dict.fromkeys(existing_parts + new_parts))
    v["particularities"] = merged[:20]

    existing["vectors"] = v


# ---------------------------------------------------------------------------
# Ingestion pipelines
# ---------------------------------------------------------------------------
def _chunk_messages(messages: list, max_tokens: int = 2000) -> list[str]:
    """Split messages into chunks of roughly max_tokens (by character estimate)."""
    chunks = []
    current = []
    current_len = 0
    for msg in messages:
        line = f"[{msg.get('time', '')}] {msg.get('content', '')}"
        line_len = len(line)
        if current_len + line_len > max_tokens * 4 and current:  # ~4 chars per token
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _ingest_wechat(wechat_dir: str | None, client_filter: str | None) -> str:
    """Ingest WeChat exported data into client profiles."""
    wdir = Path(wechat_dir) if wechat_dir else _DEFAULT_WECHAT_DIR
    chats_dir = wdir / "chats"

    if not chats_dir.exists():
        return f"WeChat export not found at {chats_dir}. Run wechat-decrypt first."

    chat_files = list(chats_dir.glob("*.json"))
    if not chat_files:
        return "No chat files found in WeChat export."

    results = []
    for chat_file in chat_files:
        chat_name = chat_file.stem
        if client_filter and client_filter.lower() not in chat_name.lower():
            continue

        messages = json.loads(chat_file.read_text())
        # Filter to text messages only
        text_msgs = [m for m in messages if m.get("type") == 1 and m.get("content")]
        if not text_msgs:
            continue

        # Load or create profile
        profile = _find_client(chat_name) or _empty_profile(chat_name, source="wechat")

        # Chunk and extract
        chunks = _chunk_messages(text_msgs)
        for chunk in chunks:
            try:
                extracted = _llm_extract(chunk)
                _merge_vectors(profile, extracted)
            except Exception as e:
                results.append(f"  Warning: extraction error for {chat_name}: {e}")

        profile["last_updated"] = datetime.now().isoformat()
        profile["raw_sources"].append({
            "file": f"wechat:{chat_name}",
            "ingested": datetime.now().isoformat(),
            "message_count": len(text_msgs),
        })
        _save_client(profile)
        results.append(f"  {chat_name}: {len(text_msgs)} messages, {len(chunks)} chunks processed")

    if not results:
        return "No matching chats found to ingest."
    return "WeChat ingestion complete:\n" + "\n".join(results)


def _ingest_folder(folder: str | None) -> str:
    """Ingest text files from inbox folder."""
    fdir = Path(folder) if folder else INBOX_DIR
    if not fdir.exists():
        return f"Inbox folder not found: {fdir}"

    files = list(fdir.glob("*.txt")) + list(fdir.glob("*.csv"))
    if not files:
        return f"No .txt or .csv files found in {fdir}"

    results = []
    for f in files:
        content = f.read_text(errors="replace")
        if not content.strip():
            continue

        # Try to guess client name from filename
        name = f.stem.replace("_", " ").replace("-", " ").title()
        profile = _find_client(name) or _empty_profile(name, source="file")

        # Chunk by ~2000 tokens
        lines = content.split("\n")
        chunk_size = 80  # ~80 lines per chunk
        for i in range(0, len(lines), chunk_size):
            chunk = "\n".join(lines[i:i + chunk_size])
            try:
                extracted = _llm_extract(chunk)
                _merge_vectors(profile, extracted)
            except Exception as e:
                results.append(f"  Warning: extraction error for {name}: {e}")

        profile["last_updated"] = datetime.now().isoformat()
        profile["raw_sources"].append({
            "file": str(f.name),
            "ingested": datetime.now().isoformat(),
            "message_count": len(lines),
        })
        _save_client(profile)
        results.append(f"  {name}: {len(lines)} lines processed from {f.name}")

    return "Folder ingestion complete:\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# Main execute
# ---------------------------------------------------------------------------
def execute(args: dict) -> str:
    action = args.get("action", "")

    if action == "ingest_wechat":
        return _ingest_wechat(args.get("wechat_dir"), args.get("client_name"))

    elif action == "ingest_folder":
        return _ingest_folder(args.get("folder"))

    elif action == "list_clients":
        profiles = []
        for f in sorted(CLIENTS_DIR.glob("*.json")):
            p = json.loads(f.read_text())
            v = p.get("vectors", {})
            prefs = v.get("preferences", {})
            budget = ""
            if prefs.get("budget_min") or prefs.get("budget_max"):
                lo = f"${prefs['budget_min']//1000}k" if prefs.get("budget_min") else "?"
                hi = f"${prefs['budget_max']//1000}k" if prefs.get("budget_max") else "?"
                budget = f" | Budget: {lo}-{hi}"
            props = len(v.get("property_history", []))
            profiles.append(
                f"  {p['name']}{budget} | {props} properties | "
                f"Source: {p.get('source', '?')} | Updated: {p.get('last_updated', '?')[:10]}"
            )
        if not profiles:
            return "No client profiles found. Use 'ingest wechat' to import conversations."
        return f"Clients ({len(profiles)}):\n" + "\n".join(profiles)

    elif action == "query":
        name = args.get("client_name", "")
        if not name:
            return "Please specify a client name."
        profile = _find_client(name)
        if not profile:
            return f"No profile found for '{name}'. Use 'list clients' to see available profiles."
        return json.dumps(profile, ensure_ascii=False, indent=2)

    elif action == "update":
        name = args.get("client_name", "")
        info = args.get("info", "")
        if not name:
            return "Please specify a client name."
        if not info:
            return "Please provide information to add."
        profile = _find_client(name) or _empty_profile(name, source="manual")
        # Use LLM to extract structured data from free-text update
        try:
            extracted = _llm_extract(f"Agent note: {info}")
            _merge_vectors(profile, extracted)
        except Exception:
            # Fallback: add as a particularity
            profile["vectors"]["particularities"].append(info)
        profile["last_updated"] = datetime.now().isoformat()
        _save_client(profile)
        return f"Updated profile for {profile['name']}."

    elif action == "delete":
        name = args.get("client_name", "")
        if not name:
            return "Please specify a client name."
        path = CLIENTS_DIR / f"{_normalize_name(name)}.json"
        if path.exists():
            path.unlink()
            return f"Deleted profile for '{name}'."
        return f"No profile found for '{name}'."

    return f"Unknown action: {action}"
