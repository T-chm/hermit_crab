"""Client Brief — pre-meeting briefing card merging client memory with property data."""

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

DEFINITION = {
    "type": "function",
    "function": {
        "name": "client_brief",
        "description": (
            "Generate a comprehensive pre-meeting briefing for a real estate client. "
            "Combines client conversation history, preferences, and property data. "
            "Use when the agent says 'prep me for', 'brief me on', or asks about "
            "a meeting with a specific client."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "client_name": {
                    "type": "string",
                    "description": "Client name (e.g. 'Zhang Wei', 'David Chen').",
                },
                "address": {
                    "type": "string",
                    "description": "Property address for the meeting/showing (optional).",
                },
            },
            "required": ["client_name"],
        },
    },
}

OLLAMA_URL = "http://localhost:11434"

ALIGNMENT_PROMPT = """\
You are a real estate assistant analyzing how well a property matches a client's preferences.

Client preferences:
{preferences}

Property details:
{property}

Produce a JSON object with:
- "matches": array of strings describing how the property meets the client's needs
- "concerns": array of strings for potential issues or unknowns
- "score": one of "Strong match", "Good match", "Moderate match", or "Weak match"

Return ONLY valid JSON, no explanation.
"""

SUMMARY_PROMPT = """\
You are a real estate assistant writing a meeting brief.
Given the client data below, write a 1-2 sentence conversational summary for each section.
Keep it natural and actionable — what should the agent know walking into this meeting?

Client data:
{client_data}

Return ONLY valid JSON with these keys:
- "recent_summary": 1-2 sentence summary of recent discussions
- "preferences_summary": 1-2 sentence summary of what they want
- "history_summary": 1-2 sentence summary of properties they've seen
- "particularities_summary": 1-2 sentence about personal details/icebreakers

No explanation, just JSON.
"""


def _llm_call(prompt: str, user_msg: str) -> dict:
    """Synchronous Ollama call, returns parsed JSON."""
    payload = json.dumps({
        "model": "qwen3.5:4b",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    content = result.get("message", {}).get("content", "")
    m = re.search(r"\{[\s\S]*\}", content)
    if m:
        return json.loads(m.group(0))
    return {}


def _fetch_client(client_name: str) -> dict | None:
    """Load client profile."""
    from tools.client_memory import _find_client
    return _find_client(client_name)


def _fetch_property(address: str) -> dict | None:
    """Try to fetch property data via property_lookup tool if available."""
    try:
        from tools.property_lookup import execute as prop_exec
        result = json.loads(prop_exec({"address": address}))
        if not result.get("error"):
            return result
    except (ImportError, Exception):
        pass
    return None


def _build_brief(client: dict, property_data: dict | None) -> dict:
    """Build the brief JSON output."""
    v = client.get("vectors", {})
    prefs = v.get("preferences", {})

    # Format preferences for display
    budget_str = ""
    if prefs.get("budget_min") or prefs.get("budget_max"):
        lo = f"${prefs['budget_min']//1000}k" if prefs.get("budget_min") else "?"
        hi = f"${prefs['budget_max']//1000}k" if prefs.get("budget_max") else "?"
        budget_str = f"{lo} - {hi}"

    # Generate summaries via LLM
    client_json = json.dumps(v, ensure_ascii=False)
    try:
        summaries = _llm_call(SUMMARY_PROMPT.format(client_data=client_json), "Generate summaries.")
    except Exception:
        summaries = {}

    brief = {
        "recent_topics": {
            "title": "Recent Discussions",
            "summary": summaries.get("recent_summary", ""),
            "items": [t.get("summary", "") for t in v.get("recent_topics", [])[-5:]],
        },
        "preferences": {
            "title": "Current Preferences",
            "summary": summaries.get("preferences_summary", ""),
            "budget": budget_str,
            "must_haves": prefs.get("must_haves", []),
            "dealbreakers": prefs.get("dealbreakers", []),
            "locations": prefs.get("locations", []),
        },
        "property_history": {
            "title": "Property History",
            "summary": summaries.get("history_summary", ""),
            "items": [
                {
                    "address": p.get("address", ""),
                    "status": p.get("status", ""),
                    "notes": p.get("notes", ""),
                }
                for p in v.get("property_history", [])
            ],
        },
        "particularities": {
            "title": "Personal Notes",
            "summary": summaries.get("particularities_summary", ""),
            "items": v.get("particularities", []),
        },
    }

    # Property alignment (if property data available)
    if property_data:
        try:
            alignment = _llm_call(
                ALIGNMENT_PROMPT.format(
                    preferences=json.dumps(prefs, ensure_ascii=False),
                    property=json.dumps(property_data, ensure_ascii=False),
                ),
                "Analyze alignment.",
            )
        except Exception:
            alignment = {"matches": [], "concerns": [], "score": "Unknown"}
        brief["property_alignment"] = {
            "title": "Property Alignment",
            "score": alignment.get("score", "Unknown"),
            "matches": alignment.get("matches", []),
            "concerns": alignment.get("concerns", []),
        }

    return brief


def execute(args: dict) -> str:
    client_name = args.get("client_name", "")
    address = args.get("address", "")

    if not client_name:
        return json.dumps({"error": "Please specify a client name."})

    # Fetch client and property in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        client_future = pool.submit(_fetch_client, client_name)
        prop_future = pool.submit(_fetch_property, address) if address else None

        client = client_future.result()
        property_data = prop_future.result() if prop_future else None

    if not client:
        return json.dumps({
            "error": f"No profile found for '{client_name}'. "
            "Use 'ingest wechat' to import conversations first."
        })

    brief = _build_brief(client, property_data)

    output = {
        "client_name": client.get("name", client_name),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "property": property_data,
        "brief": brief,
        "error": None,
    }

    return json.dumps(output, ensure_ascii=False)
