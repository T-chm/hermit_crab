"""Google Calendar — view agenda, create events, check schedule via Google API Python client."""

import json
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from ._google_auth import get_credentials

DEFINITION = {
    "type": "function",
    "function": {
        "name": "calendar",
        "description": (
            "Access Google Calendar: view today's agenda, upcoming events, create events. "
            "ONLY use when the user explicitly asks about their "
            "schedule, calendar, meetings, events, or availability."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["agenda", "today", "tomorrow", "week", "create", "search"],
                    "description": (
                        "agenda: show upcoming events (next few days). "
                        "today: show today's events. "
                        "tomorrow: show tomorrow's events. "
                        "week: show this week's events. "
                        "create: create a new event. "
                        "search: search for events by keyword."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Event title for 'create' action.",
                },
                "start": {
                    "type": "string",
                    "description": "Start time ISO format for 'create' (e.g. '2026-03-13T10:00:00').",
                },
                "end": {
                    "type": "string",
                    "description": "End time ISO format for 'create'. Defaults to 1 hour after start.",
                },
                "attendees": {
                    "type": "string",
                    "description": "Comma-separated attendee emails for 'create' action.",
                },
                "query": {
                    "type": "string",
                    "description": "Search keyword for 'search' action.",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days to look ahead for 'agenda' action (default 3).",
                },
            },
            "required": ["action"],
        },
    },
}


def _get_service():
    creds = get_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_time(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return iso


def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a, %b %d")
    except Exception:
        return iso


def _parse_events(items: list) -> list[dict]:
    events = []
    for item in items:
        start = item.get("start", {})
        end = item.get("end", {})
        start_dt = start.get("dateTime") or start.get("date", "")
        end_dt = end.get("dateTime") or end.get("date", "")
        is_all_day = "date" in start and "dateTime" not in start

        attendees = []
        for a in item.get("attendees", [])[:5]:
            attendees.append({
                "email": a.get("email", ""),
                "name": a.get("displayName", ""),
                "status": a.get("responseStatus", ""),
            })

        events.append({
            "id": item.get("id", ""),
            "title": item.get("summary", "(No title)"),
            "start": start_dt,
            "end": end_dt,
            "start_time": "" if is_all_day else _fmt_time(start_dt),
            "end_time": "" if is_all_day else _fmt_time(end_dt),
            "date": _fmt_date(start_dt),
            "all_day": is_all_day,
            "location": item.get("location", ""),
            "status": item.get("status", ""),
            "organizer": item.get("organizer", {}).get("email", ""),
            "hangout": item.get("hangoutLink", ""),
            "attendees": attendees,
            "description": (item.get("description") or "")[:200],
        })
    return events


def _list_events(service, time_min: str, time_max: str, max_results: int = 20, query: str = "") -> list[dict]:
    kwargs = {
        "calendarId": "primary",
        "timeMin": time_min,
        "timeMax": time_max,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if query:
        kwargs["q"] = query

    resp = service.events().list(**kwargs).execute()
    return _parse_events(resp.get("items", []))


def execute(args: dict) -> str:
    action = args.get("action", "agenda")
    now = _now()

    try:
        service = _get_service()
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Auth failed: {e}. Try deleting ~/.hermit_crab/google_token.json and retry."})

    if action == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        try:
            events = _list_events(service, start.isoformat(), end.isoformat())
            return json.dumps({"action": "today", "date": start.strftime("%a, %b %d"), "events": events})
        except Exception as e:
            return json.dumps({"action": "today", "error": str(e)})

    if action == "tomorrow":
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        try:
            events = _list_events(service, start.isoformat(), end.isoformat())
            return json.dumps({"action": "tomorrow", "date": start.strftime("%a, %b %d"), "events": events})
        except Exception as e:
            return json.dumps({"action": "tomorrow", "error": str(e)})

    if action == "week":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        try:
            events = _list_events(service, start.isoformat(), end.isoformat())
            return json.dumps({"action": "week", "start_date": start.strftime("%a, %b %d"),
                               "end_date": end.strftime("%a, %b %d"), "events": events})
        except Exception as e:
            return json.dumps({"action": "week", "error": str(e)})

    if action == "agenda":
        days = args.get("days", 3)
        start = now
        end = now + timedelta(days=days)
        try:
            events = _list_events(service, start.isoformat(), end.isoformat())
            return json.dumps({"action": "agenda", "days": days, "events": events})
        except Exception as e:
            return json.dumps({"action": "agenda", "error": str(e)})

    if action == "search":
        query = args.get("query", "")
        if not query:
            return json.dumps({"action": "search", "error": "Please specify a search query."})
        start = now - timedelta(days=30)
        end = now + timedelta(days=60)
        try:
            events = _list_events(service, start.isoformat(), end.isoformat(), query=query)
            return json.dumps({"action": "search", "query": query, "events": events})
        except Exception as e:
            return json.dumps({"action": "search", "error": str(e)})

    if action == "create":
        title = args.get("title", "")
        if not title:
            return json.dumps({"action": "create", "error": "Please specify an event title."})

        start_str = args.get("start", "")
        end_str = args.get("end", "")
        attendees_str = args.get("attendees", "")

        if not start_str:
            return json.dumps({"action": "create", "error": "Please specify a start time."})

        # Parse start/end
        event_body = {"summary": title}

        # Determine if it's a date or datetime
        if "T" in start_str:
            event_body["start"] = {"dateTime": start_str, "timeZone": "UTC"}
            if end_str and "T" in end_str:
                event_body["end"] = {"dateTime": end_str, "timeZone": "UTC"}
            else:
                # Default 1 hour
                try:
                    st = datetime.fromisoformat(start_str)
                    et = st + timedelta(hours=1)
                    event_body["end"] = {"dateTime": et.isoformat(), "timeZone": "UTC"}
                except Exception:
                    event_body["end"] = event_body["start"]
        else:
            event_body["start"] = {"date": start_str}
            event_body["end"] = {"date": end_str or start_str}

        if attendees_str:
            event_body["attendees"] = [{"email": e.strip()} for e in attendees_str.split(",") if e.strip()]

        try:
            created = service.events().insert(calendarId="primary", body=event_body).execute()
            return json.dumps({
                "action": "create",
                "title": title,
                "start": start_str,
                "end": end_str,
                "attendees": attendees_str,
                "status": "created",
                "link": created.get("htmlLink", ""),
            })
        except Exception as e:
            return json.dumps({"action": "create", "error": str(e)})

    return json.dumps({"error": f"Unknown action: {action}"})
