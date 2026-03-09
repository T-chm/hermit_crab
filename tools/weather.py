"""Weather — current conditions and forecasts via wttr.in (no API key needed)."""

import subprocess
import urllib.parse

DEFINITION = {
    "type": "function",
    "function": {
        "name": "weather",
        "description": (
            "Get current weather conditions and forecasts for a location. "
            "ONLY use when the user explicitly asks about weather, temperature, "
            "or forecasts. Do NOT call for greetings or general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or location (e.g. 'London', 'New York', 'Tokyo')",
                },
                "detail": {
                    "type": "string",
                    "enum": ["brief", "current", "forecast"],
                    "description": (
                        "brief: one-line summary. "
                        "current: detailed current conditions. "
                        "forecast: 3-day forecast."
                    ),
                },
            },
            "required": ["location"],
        },
    },
}


def execute(args: dict) -> str:
    location = args.get("location", "")
    detail = args.get("detail", "brief")

    if not location:
        return "Please specify a location."

    loc = urllib.parse.quote(location)

    if detail == "current":
        url = f"wttr.in/{loc}?0"
    elif detail == "forecast":
        url = f"wttr.in/{loc}"
    else:
        url = f"wttr.in/{loc}?format=%l:+%c+%t+(feels+like+%f),+%w+wind,+%h+humidity"

    try:
        r = subprocess.run(
            ["curl", "-s", url],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return f"Could not fetch weather: {r.stderr.strip()}"
        output = r.stdout.strip()
        if not output:
            return f"No weather data found for '{location}'."
        return output
    except subprocess.TimeoutExpired:
        return "Weather request timed out."
    except Exception as e:
        return f"Weather error: {e}"
