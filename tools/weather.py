"""Weather — current conditions and forecasts via Open-Meteo (free, no API key)."""

import json
import urllib.parse
import urllib.request

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

_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Light freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "HermitCrab/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _geocode(location: str) -> tuple[str, float, float]:
    """Return (display_name, lat, lon) for a city name."""
    url = (
        "https://geocoding-api.open-meteo.com/v1/search?"
        f"name={urllib.parse.quote(location)}&count=1&language=en"
    )
    data = _fetch_json(url)
    results = data.get("results")
    if not results:
        raise ValueError(f"Location '{location}' not found.")
    r = results[0]
    name = r.get("name", location)
    country = r.get("country", "")
    display = f"{name}, {country}" if country else name
    return display, r["latitude"], r["longitude"]


def _describe_code(code: int) -> str:
    return _WMO_CODES.get(code, "Unknown")


def execute(args: dict) -> str:
    location = args.get("location", "")
    detail = args.get("detail", "brief")

    if not location:
        return "Please specify a location."

    try:
        display, lat, lon = _geocode(location)
    except ValueError as e:
        return str(e)
    except Exception:
        return f"Could not look up location '{location}'."

    try:
        if detail == "forecast":
            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                f"precipitation_probability_max,wind_speed_10m_max"
                f"&timezone=auto&forecast_days=3"
            )
            data = _fetch_json(url)
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            lines = [f"3-day forecast for {display}:"]
            for i, date in enumerate(dates):
                code = daily["weather_code"][i]
                hi = daily["temperature_2m_max"][i]
                lo = daily["temperature_2m_min"][i]
                rain = daily["precipitation_probability_max"][i]
                wind = daily["wind_speed_10m_max"][i]
                lines.append(
                    f"  {date}: {_describe_code(code)}, "
                    f"{lo}-{hi}C, {rain}% rain chance, wind {wind} km/h"
                )
            return "\n".join(lines)
        else:
            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,"
                f"apparent_temperature,weather_code,wind_speed_10m"
                f"&timezone=auto"
            )
            data = _fetch_json(url)
            c = data.get("current", {})
            temp = c.get("temperature_2m")
            feels = c.get("apparent_temperature")
            humidity = c.get("relative_humidity_2m")
            code = c.get("weather_code", 0)
            wind = c.get("wind_speed_10m")
            cond = _describe_code(code)

            if detail == "brief":
                return f"{display}: {temp}C, {cond}, feels like {feels}C"
            else:
                return (
                    f"{display}: {temp}C ({cond})\n"
                    f"  Feels like: {feels}C\n"
                    f"  Humidity: {humidity}%\n"
                    f"  Wind: {wind} km/h"
                )
    except Exception as e:
        return f"Weather error: {e}"
