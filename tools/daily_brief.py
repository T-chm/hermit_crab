"""Daily Brief — aggregated dashboard with weather, stocks, email, trips, and music."""

import json
import random
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

DEFINITION = {
    "type": "function",
    "function": {
        "name": "daily_brief",
        "description": (
            "Get a daily briefing with weather, stock watchlist, unread emails, "
            "upcoming trips, and a music suggestion. "
            "Use when the user asks for a daily brief, morning summary, or status update."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City for weather (default: auto-detect from IP).",
                },
                "watchlist": {
                    "type": "string",
                    "description": "Comma-separated stock/crypto symbols (default: major indices).",
                },
            },
        },
    },
}

# Music vibes by time of day
_MUSIC_VIBES = {
    "morning": [
        ("Morning Energy", "upbeat morning playlist"),
        ("Coffee & Chill", "chill morning acoustic"),
        ("Wake Up", "energetic pop morning"),
        ("Sunny Day", "feel good indie morning"),
    ],
    "afternoon": [
        ("Afternoon Focus", "focus concentration instrumental"),
        ("Midday Groove", "upbeat afternoon pop"),
        ("Work Mode", "lo-fi beats study"),
        ("Chill Vibes", "chill afternoon mix"),
    ],
    "evening": [
        ("Evening Wind Down", "relaxing evening acoustic"),
        ("Dinner Jazz", "smooth jazz dinner"),
        ("Golden Hour", "indie evening chill"),
        ("Sunset Vibes", "chillwave sunset"),
    ],
    "night": [
        ("Late Night", "late night r&b"),
        ("Night Owl", "ambient electronic night"),
        ("Midnight Jazz", "midnight jazz piano"),
        ("Dream State", "dreamy ambient sleep"),
    ],
}


def _get_time_of_day() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    return "night"


_GREETINGS = {
    "morning": "Good morning",
    "afternoon": "Good afternoon",
    "evening": "Good evening",
    "night": "Hey there",
}


def _fetch_weather(location: str) -> dict:
    """Fetch one-line weather via Open-Meteo (free, no API key)."""
    try:
        from tools.weather import _geocode, _describe_code, _fetch_json
        loc = location if location else "Singapore"
        display, lat, lon = _geocode(loc)
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,apparent_temperature,weather_code"
            f"&timezone=auto"
        )
        data = _fetch_json(url)
        c = data.get("current", {})
        temp = c.get("temperature_2m")
        feels = c.get("apparent_temperature")
        cond = _describe_code(c.get("weather_code", 0))
        text = f"{display}: {temp}C, {cond}, feels like {feels}C"
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _fetch_stocks(symbols: list[str]) -> dict:
    """Fetch stock watchlist or market overview."""
    try:
        from tools.stocks import execute as stocks_exec
        if symbols:
            result = stocks_exec({"action": "watchlist", "symbols": ",".join(symbols)})
        else:
            result = stocks_exec({"action": "market"})
        data = json.loads(result)
        if data.get("error"):
            return {"ok": False, "error": data["error"]}
        return {"ok": True, "data": data.get("data", []), "action": data.get("action", "market")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _fetch_emails() -> dict:
    """Fetch unread email summary."""
    try:
        from tools.gmail import execute as gmail_exec
        result = gmail_exec({"action": "unread", "max_results": 3})
        data = json.loads(result)
        if data.get("error"):
            return {"ok": False, "error": data["error"]}
        return {"ok": True, "total": data.get("total", 0), "emails": data.get("emails", [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _fetch_trips() -> dict:
    """Fetch upcoming trips."""
    try:
        from tools.trips import execute as trips_exec
        result = trips_exec({"action": "scan", "days_ahead": 90})
        data = json.loads(result)
        if data.get("error"):
            return {"ok": False, "error": data["error"]}
        return {"ok": True, "trips": data.get("trips", []), "total": data.get("total_found", 0)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _load_memory_defaults() -> tuple[str, list[str]]:
    """Read location and stock watchlist from the user's core memory facts."""
    import pathlib
    mem_path = pathlib.Path.home() / ".hermit_crab" / "memory.json"
    location = ""
    symbols: list[str] = []
    if not mem_path.exists():
        return location, symbols
    try:
        facts = json.loads(mem_path.read_text()).get("facts", [])
    except Exception:
        return location, symbols
    for fact in facts:
        fl = fact.lower()
        # Location
        if not location and "location:" in fl:
            location = fact.split(":", 1)[1].strip()
        # Stock watchlist — collect tickers, keep the longest match
        if "watchlist" in fl or "monitored" in fl or "list includes" in fl or "stock" in fl:
            import re as _re
            tickers = _re.findall(r"\(([A-Z]{1,5})\)", fact)
            if len(tickers) > len(symbols):
                symbols = tickers
    return location, symbols


def execute(args: dict) -> str:
    # Explicit args override memory defaults
    mem_location, mem_symbols = _load_memory_defaults()
    location = args.get("location", "") or mem_location
    watchlist_raw = args.get("watchlist", "")
    symbols = [s.strip().upper() for s in watchlist_raw.split(",") if s.strip()] if watchlist_raw else mem_symbols

    now = datetime.now()
    time_of_day = _get_time_of_day()
    greeting = _GREETINGS.get(time_of_day, "Hello")

    # Pick a random music suggestion for the time of day
    vibes = _MUSIC_VIBES.get(time_of_day, _MUSIC_VIBES["morning"])
    music_vibe, music_query = random.choice(vibes)

    # Run all fetches in parallel
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_fetch_weather, location): "weather",
            pool.submit(_fetch_stocks, symbols): "stocks",
            pool.submit(_fetch_emails): "emails",
            pool.submit(_fetch_trips): "trips",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"ok": False, "error": str(e)}

    return json.dumps({
        "greeting": greeting,
        "time_of_day": time_of_day,
        "date": now.strftime("%A, %B %-d, %Y"),
        "time": now.strftime("%-I:%M %p"),
        "weather": results.get("weather", {"ok": False, "error": "Not fetched"}),
        "stocks": results.get("stocks", {"ok": False, "error": "Not fetched"}),
        "emails": results.get("emails", {"ok": False, "error": "Not fetched"}),
        "trips": results.get("trips", {"ok": False, "error": "Not fetched"}),
        "music": {
            "vibe": music_vibe,
            "query": music_query,
        },
    })
