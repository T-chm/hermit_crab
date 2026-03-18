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
                "language": {
                    "type": "string",
                    "enum": ["en", "zh"],
                    "description": "Output language: en for English (default), zh for Chinese.",
                },
            },
            "required": ["client_name"],
        },
    },
}

OLLAMA_URL = "http://localhost:11434"

ALIGNMENT_PROMPT = {
    "en": """\
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
""",
    "zh": """\
你是一个房地产助手，分析房产与客户需求的匹配程度。

客户需求：
{preferences}

房产详情：
{property}

生成一个JSON对象：
- "matches": 字符串数组，描述房产如何满足客户需求
- "concerns": 字符串数组，列出潜在问题或未知项
- "score": "非常匹配"、"比较匹配"、"一般匹配"或"不太匹配"之一

只返回有效JSON，不要解释。
""",
}

SUMMARY_PROMPT = {
    "en": """\
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
""",
    "zh": """\
你是一个房地产助手，正在撰写客户会面简报。
根据以下客户资料，为每个部分写1-2句简洁实用的摘要。
语气自然，重点是经纪人在见面前需要知道什么。

客户资料：
{client_data}

只返回有效JSON，包含以下字段：
- "recent_summary": 1-2句最近沟通摘要
- "preferences_summary": 1-2句客户需求摘要
- "history_summary": 1-2句看房历史摘要
- "particularities_summary": 1-2句个人细节/破冰话题

只返回JSON，不要解释。
""",
}

SECTION_TITLES = {
    "en": {
        "recent_topics": "Recent Discussions",
        "preferences": "Current Preferences",
        "property_history": "Property History",
        "particularities": "Personal Notes",
        "property_alignment": "Property Alignment",
    },
    "zh": {
        "recent_topics": "最近沟通",
        "preferences": "当前需求",
        "property_history": "看房记录",
        "particularities": "个人备注",
        "property_alignment": "房产匹配分析",
    },
}


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


TRANSLATE_PROMPT = """\
Translate ALL the following items to Chinese. Keep proper nouns (addresses, names) as-is.
Return ONLY a valid JSON object with the same keys, values translated to Chinese.

{data}
"""

STATUS_ZH = {
    "rejected": "已拒绝",
    "liked": "感兴趣",
    "shown": "已看房",
    "pending": "待看房",
    "scheduled": "已安排",
}


def _build_brief(client: dict, property_data: dict | None, lang: str = "en") -> dict:
    """Build the brief JSON output."""
    v = client.get("vectors", {})
    prefs = v.get("preferences", {})
    titles = SECTION_TITLES.get(lang, SECTION_TITLES["en"])

    # Format preferences for display
    budget_str = ""
    if prefs.get("budget_min") or prefs.get("budget_max"):
        lo = f"${prefs['budget_min']//1000}k" if prefs.get("budget_min") else "?"
        hi = f"${prefs['budget_max']//1000}k" if prefs.get("budget_max") else "?"
        budget_str = f"{lo} - {hi}"

    # Raw items from profile
    recent_items = [t.get("summary", "") for t in v.get("recent_topics", [])[-5:]]
    must_haves = prefs.get("must_haves", [])
    dealbreakers = prefs.get("dealbreakers", [])
    locations = prefs.get("locations", [])
    prop_history = [
        {
            "address": p.get("address", ""),
            "status": p.get("status", ""),
            "notes": p.get("notes", ""),
        }
        for p in v.get("property_history", [])
    ]
    particularities = v.get("particularities", [])

    # For Chinese mode: translate all raw items in one LLM call
    if lang == "zh":
        translate_data = {
            "recent_items": recent_items,
            "must_haves": must_haves,
            "dealbreakers": dealbreakers,
            "property_notes": [p["notes"] for p in prop_history],
            "particularities": particularities,
        }
        try:
            translated = _llm_call(
                TRANSLATE_PROMPT.format(data=json.dumps(translate_data, ensure_ascii=False)),
                "Translate to Chinese.",
            )
            recent_items = translated.get("recent_items", recent_items)
            must_haves = translated.get("must_haves", must_haves)
            dealbreakers = translated.get("dealbreakers", dealbreakers)
            translated_notes = translated.get("property_notes", [])
            for i, note in enumerate(translated_notes):
                if i < len(prop_history):
                    prop_history[i]["notes"] = note
            particularities = translated.get("particularities", particularities)
        except Exception:
            pass  # Fall back to English items

        # Translate status labels
        for p in prop_history:
            p["status"] = STATUS_ZH.get(p["status"], p["status"])

    # Generate summaries via LLM
    client_json = json.dumps(v, ensure_ascii=False)
    prompt = SUMMARY_PROMPT.get(lang, SUMMARY_PROMPT["en"])
    try:
        summaries = _llm_call(prompt.format(client_data=client_json), "Generate summaries.")
    except Exception:
        summaries = {}

    brief = {
        "recent_topics": {
            "title": titles["recent_topics"],
            "summary": summaries.get("recent_summary", ""),
            "items": recent_items,
        },
        "preferences": {
            "title": titles["preferences"],
            "summary": summaries.get("preferences_summary", ""),
            "budget": budget_str,
            "must_haves": must_haves,
            "dealbreakers": dealbreakers,
            "locations": locations,
        },
        "property_history": {
            "title": titles["property_history"],
            "summary": summaries.get("history_summary", ""),
            "items": prop_history,
        },
        "particularities": {
            "title": titles["particularities"],
            "summary": summaries.get("particularities_summary", ""),
            "items": particularities,
        },
    }

    # Property alignment (if property data available)
    if property_data:
        align_prompt = ALIGNMENT_PROMPT.get(lang, ALIGNMENT_PROMPT["en"])
        try:
            alignment = _llm_call(
                align_prompt.format(
                    preferences=json.dumps(prefs, ensure_ascii=False),
                    property=json.dumps(property_data, ensure_ascii=False),
                ),
                "Analyze alignment.",
            )
        except Exception:
            alignment = {"matches": [], "concerns": [], "score": "Unknown"}
        brief["property_alignment"] = {
            "title": titles["property_alignment"],
            "score": alignment.get("score", "Unknown"),
            "matches": alignment.get("matches", []),
            "concerns": alignment.get("concerns", []),
        }

    return brief


def execute(args: dict) -> str:
    client_name = args.get("client_name", "")
    address = args.get("address", "")
    lang = args.get("language", "en")

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

    brief = _build_brief(client, property_data, lang=lang)

    output = {
        "client_name": client.get("name", client_name),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "language": lang,
        "property": property_data,
        "brief": brief,
        "error": None,
    }

    return json.dumps(output, ensure_ascii=False)
