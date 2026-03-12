"""Trips — smart travel assistant that cross-references Gmail and Calendar."""

import base64
import json
import re
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from ._google_auth import get_credentials

DEFINITION = {
    "type": "function",
    "function": {
        "name": "trips",
        "description": (
            "Smart travel assistant: finds upcoming trips from email confirmations "
            "(flights, hotels, Airbnb, car rentals) and cross-references with your calendar. "
            "Can also create calendar events or reminders for trips not yet on your calendar. "
            "Use when the user asks about upcoming trips, travel plans, or flight/hotel info."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["scan", "create_events"],
                    "description": (
                        "scan: search emails and calendar for upcoming trips, show what's found and what's missing. "
                        "create_events: create calendar events for trips that don't have one yet."
                    ),
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "How many days ahead to look (default 90).",
                },
            },
            "required": ["action"],
        },
    },
}

# Gmail search queries for travel-related emails
_TRAVEL_QUERIES = [
    "subject:(flight confirmation OR booking confirmation OR itinerary OR e-ticket)",
    "subject:(hotel reservation OR hotel confirmation)",
    "from:(airbnb.com OR booking.com OR expedia.com OR hotels.com OR agoda.com) subject:(reservation OR confirmation OR booking)",
    "from:(united.com OR delta.com OR aa.com OR southwest.com OR jetblue.com "
    "OR singaporeair.com OR cathaypacific.com OR emirates.com OR klm.com "
    "OR airasia.com OR scoot.com OR flyscoot.com) subject:(confirmation OR itinerary OR booking)",
    "from:(trip.com) subject:(booking confirmation OR confirmation number)",
    # Catch-all for booking agents and smaller OTAs
    'subject:("e-ticket itinerary" OR "electronic itinerary" OR "ticket completed" OR "ticket is completed")',
    'subject:("ticket order confirmation" OR "booking confirmed" OR "flight booking confirmed")',
    "subject:(boarding pass OR flight itinerary OR trip confirmation)",
    "subject:(car rental OR rental confirmation) from:(hertz OR avis OR enterprise OR sixt)",
    "subject:(train ticket OR rail confirmation OR bus ticket)",
]

# Subjects that are NOT actual bookings (policy updates, marketing, check-in tips, etc.)
_NOISE_PATTERNS = [
    r"\b(?:policy|update|terms|privacy|newsletter|promo|offer|deal|sale|unsubscribe)\b",
    r"\b(?:survey|feedback|review|rate your|how was)\b",
    r"\b(?:earn|miles|points|reward|loyalty|upgrade offer)\b",
]

# Date patterns to extract from email snippets/subjects
_DATE_PATTERNS = [
    # "Mar 15, 2026" / "March 15, 2026"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}",
    # "15 Mar 2026" / "15 March 2026" / "15th Mar 2026" / "24th July 2026"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}",
    # "2026-03-15"
    r"\d{4}-\d{2}-\d{2}",
    # "03/15/2026" or "15/03/2026"
    r"\d{1,2}/\d{1,2}/\d{4}",
]

_DATE_FORMATS = [
    "%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y",
    "%d %b %Y", "%d %B %Y",
    "%Y-%m-%d",
    "%m/%d/%Y", "%d/%m/%Y",
]

# Keywords that indicate travel type
_TYPE_KEYWORDS = {
    "flight": ["flight", "boarding", "airline", "depart", "arrive", "terminal", "gate", "e-ticket", "itinerary"],
    "hotel": ["hotel", "check-in", "check-out", "reservation", "room", "accommodation", "stay"],
    "event": ["festival", "concert", "ticket order", "event", "show", "performance"],
    "airbnb": ["airbnb", "host", "listing"],
    "car_rental": ["car rental", "rental car", "pickup", "hertz", "avis", "enterprise", "sixt"],
    "train": ["train", "rail", "amtrak", "eurostar"],
}

# Location extraction patterns
_LOCATION_PATTERNS = [
    r"(?:to|arriving?|destination|depart(?:ing|ure)?)\s*:?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
    r"(?:SIN|LAX|JFK|SFO|LHR|NRT|HND|CDG|ICN|BKK|HKG|TPE|KUL|CGK|MNL|PEK|PVG|DXB|DOH)\b",
]


def _get_services():
    creds = get_credentials()
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    calendar = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return gmail, calendar


def _parse_date_match(match_str: str) -> datetime | None:
    """Try to parse a date string against known formats."""
    date_str = match_str.replace(".", "")
    date_str = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", date_str)
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.year >= datetime.now().year:
                return dt
        except ValueError:
            continue
    return None


def _extract_dates(text: str) -> list[datetime]:
    """Extract dates from text using multiple patterns."""
    dates = []
    for pattern in _DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            dt = _parse_date_match(match.group(0))
            if dt:
                dates.append(dt)
    return sorted(set(dates))


def _extract_checkin_dates(text: str) -> list[datetime]:
    """Extract check-in/check-out or departure/arrival dates specifically.

    Looks for dates near contextual keywords like 'check-in', 'check-out',
    'depart', 'arrive'. Falls back to _extract_dates if no contextual dates found.
    """
    context_patterns = [
        r"check[\s-]*in[:\s]*",
        r"check[\s-]*out[:\s]*",
        r"depart(?:ure|ing)?[:\s]*",
        r"arriv(?:al|ing)?[:\s]*",
        r"(?:from|outbound)[:\s]*",
        r"(?:return|inbound)[:\s]*",
    ]
    dates = []
    for ctx_pat in context_patterns:
        for date_pat in _DATE_PATTERNS:
            # Date within 30 chars after the context keyword
            combined = ctx_pat + r".{0,30}?" + "(" + date_pat + ")"
            for match in re.finditer(combined, text, re.IGNORECASE):
                dt = _parse_date_match(match.group(1))
                if dt:
                    dates.append(dt)
    if dates:
        return sorted(set(dates))
    # Fallback: return all dates
    return _extract_dates(text)


def _detect_type(text: str) -> str:
    """Detect travel type from text."""
    lower = text.lower()
    for trip_type, keywords in _TYPE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return trip_type
    return "travel"


def _extract_locations(text: str) -> list[str]:
    """Extract location names and airport codes."""
    locations = []
    # Airport codes (3-letter uppercase)
    codes = re.findall(r"\b([A-Z]{3})\b", text)
    known_codes = {"SIN", "LAX", "JFK", "SFO", "LHR", "NRT", "HND", "CDG", "ICN",
                   "BKK", "HKG", "TPE", "KUL", "CGK", "MNL", "PEK", "PVG", "DXB",
                   "DOH", "ORD", "ATL", "DEN", "DFW", "SEA", "MIA", "BOS", "EWR",
                   "IAD", "FRA", "AMS", "FCO", "BCN", "MAD", "IST", "MEL", "SYD",
                   "NRT", "KIX", "CTS", "ITM", "DEL", "BOM", "CCU"}
    for code in codes:
        if code in known_codes:
            locations.append(code)
    # City names after "to" or "from"
    # Only match clean text (no newlines/tabs in location names)
    clean_text = re.sub(r"[\n\r\t]+", " ", text)
    _STOP_WORDS = {"the", "your", "this", "that", "our", "my", "a", "an", "all",
                   "dear", "chen", "hongmin", "booking", "thank", "please", "email",
                   "no", "number", "baggage", "allowance", "legs", "telephone",
                   "seven", "receipt", "confirmation", "confirmed", "view", "manage",
                   "avoid", "note", "important", "click", "here", "below", "above",
                   "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                   "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
                   "january", "february", "march", "april", "june", "july", "august",
                   "september", "october", "november", "december",
                   "special", "approx", "total", "price", "amount", "details",
                   "contact", "refund", "policy", "cancel", "change", "modify"}
    # City / place names — only keep things that look like real locations
    # Use "to/from PLACE" pattern but validate against known places or multi-word names with Hotel/Airport
    _PLACE_INDICATORS = {"hotel", "airport", "city", "island", "beach", "station", "resort", "park"}
    for m in re.finditer(r"(?:to|from|in|at)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", clean_text):
        loc = m.group(1).strip()
        words = loc.lower().split()
        if any(w in _STOP_WORDS for w in words):
            continue
        # Accept if contains a place indicator word OR is a known place pattern
        has_indicator = any(w in _PLACE_INDICATORS for w in words)
        is_multi = len(words) >= 2 and has_indicator
        # For single words, only keep if 6+ chars (likely a real city name)
        if is_multi or (len(words) == 1 and len(loc) >= 6):
            locations.append(loc)
    return list(dict.fromkeys(locations))[:3]  # dedupe, max 3


def _extract_headers(headers: list, *names: str) -> dict:
    want = {n.lower() for n in names}
    result = {}
    for h in headers:
        if h["name"].lower() in want:
            result[h["name"].lower()] = h["value"]
    return result


def _extract_body_text(payload: dict) -> str:
    """Extract text from a full-format Gmail message payload.

    Recursively walks the MIME tree to find text/plain or text/html at any depth.
    """
    # Collect all text parts recursively
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def _walk(node: dict):
        mime = node.get("mimeType", "")
        data = node.get("body", {}).get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if "text/plain" in mime:
                plain_parts.append(decoded)
            elif "text/html" in mime:
                html_parts.append(decoded)
        for part in node.get("parts", []):
            _walk(part)

    _walk(payload)

    if plain_parts:
        return plain_parts[0][:5000]
    if html_parts:
        # Strip HTML tags, collapse whitespace to get readable text
        text = re.sub(r"<style[^>]*>.*?</style>", " ", html_parts[0], flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text[:5000]
    return ""


def _is_noise(subject: str, snippet: str) -> bool:
    """Return True if this email is a policy update, marketing, etc. — not a real booking."""
    text = f"{subject} {snippet}".lower()
    for pat in _NOISE_PATTERNS:
        if re.search(pat, text):
            # But if it also has strong booking signals, keep it
            if re.search(r"\b(?:confirmation|itinerary|booking|reservation)\s*(?:#|number|code)", text):
                return False
            return True
    return False


def _scan_emails(gmail, days_ahead: int) -> list[dict]:
    """Search Gmail for travel-related emails and extract trip info."""
    now = datetime.now(timezone.utc)
    today = now.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    after_date = now - timedelta(days=180)
    after_str = after_date.strftime("%Y/%m/%d")

    # --- Phase 1: Combine queries into 2 big OR queries (fewer API calls) ---
    all_msg_ids: set[str] = set()
    all_messages: list[dict] = []

    # Split into 2 batches to stay under Gmail query length limits
    mid = len(_TRAVEL_QUERIES) // 2
    query_batches = [
        " OR ".join(f"({q})" for q in _TRAVEL_QUERIES[:mid]),
        " OR ".join(f"({q})" for q in _TRAVEL_QUERIES[mid:]),
    ]

    for combined_q in query_batches:
        try:
            resp = gmail.users().messages().list(
                userId="me", q=f"({combined_q}) after:{after_str}", maxResults=15,
            ).execute()
            for msg in resp.get("messages", []):
                if msg["id"] not in all_msg_ids:
                    all_msg_ids.add(msg["id"])
                    all_messages.append(msg)
        except Exception:
            continue

    msg_ids = [m["id"] for m in all_messages[:25]]
    if not msg_ids:
        return []

    # --- Phase 2: Batch metadata fetch (single HTTP request) ---
    meta_results: dict[str, dict] = {}

    def _meta_callback(request_id, response, exception):
        if not exception and response:
            meta_results[request_id] = response

    batch = gmail.new_batch_http_request(callback=_meta_callback)
    for mid in msg_ids:
        batch.add(
            gmail.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ),
            request_id=mid,
        )
    batch.execute()

    # --- Phase 3: Filter and identify which need full-body fetch ---
    needs_full: list[str] = []
    meta_info: dict[str, dict] = {}
    seen_subjects: set[str] = set()

    for mid in msg_ids:
        detail = meta_results.get(mid)
        if not detail:
            continue

        headers = _extract_headers(detail.get("payload", {}).get("headers", []),
                                   "from", "subject", "date")
        subject = headers.get("subject", "")
        snippet = detail.get("snippet", "")
        full_text = f"{subject} {snippet}"

        if _is_noise(subject, snippet):
            continue

        subj_key = re.sub(r"\W+", " ", subject.lower()).strip()[:50]
        if subj_key in seen_subjects:
            continue
        seen_subjects.add(subj_key)

        dates = _extract_dates(full_text)
        future_dates = [d for d in dates if d >= today]

        meta_info[mid] = {
            "subject": subject, "snippet": snippet, "full_text": full_text,
            "headers": headers, "dates": dates, "future_dates": future_dates,
        }

        if not future_dates:
            needs_full.append(mid)

    # --- Phase 4: Batch full-body fetch (single HTTP request) ---
    if needs_full:
        full_results: dict[str, dict] = {}

        def _full_callback(request_id, response, exception):
            if not exception and response:
                full_results[request_id] = response

        batch = gmail.new_batch_http_request(callback=_full_callback)
        for mid in needs_full:
            batch.add(
                gmail.users().messages().get(userId="me", id=mid, format="full"),
                request_id=mid,
            )
        batch.execute()

        for mid, detail in full_results.items():
            if mid not in meta_info:
                continue
            body_text = _extract_body_text(detail.get("payload", {}))
            if body_text:
                info = meta_info[mid]
                combined = f"{info['subject']} {body_text}"
                dates = _extract_checkin_dates(combined)
                future_dates = [d for d in dates if d >= today]
                info["dates"] = dates
                info["future_dates"] = future_dates
                info["full_text"] = combined
                info["body_text"] = body_text

    # --- Phase 5: Build trip list ---
    trips = []
    for mid, info in meta_info.items():
        future_dates = info["future_dates"]
        if not future_dates:
            continue

        full_text = info["full_text"]
        trip_type = _detect_type(full_text)
        body_text = info.get("body_text", "")
        search_text = f"{info['subject']} {info['snippet']} {body_text}" if body_text else f"{info['subject']} {info['snippet']}"
        locations = _extract_locations(search_text)

        trips.append({
            "email_id": mid,
            "subject": info["subject"],
            "from": info["headers"].get("from", ""),
            "email_date": info["headers"].get("date", ""),
            "snippet": info["snippet"][:200],
            "type": trip_type,
            "dates": [d.strftime("%Y-%m-%d") for d in future_dates[:4]],
            "locations": locations[:3],
            "has_calendar_event": False,
        })

    trips.sort(key=lambda t: t["dates"][0] if t["dates"] else "9999")
    return trips


def _check_calendar(calendar_svc, trips: list[dict], days_ahead: int) -> list[dict]:
    """Check which trips already have calendar events."""
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=2)).isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    try:
        events_resp = calendar_svc.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=100,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        cal_events = events_resp.get("items", [])
    except Exception:
        cal_events = []

    # Build a set of calendar event keywords for matching
    cal_texts = []
    for ev in cal_events:
        title = (ev.get("summary") or "").lower()
        desc = (ev.get("description") or "").lower()
        loc = (ev.get("location") or "").lower()
        cal_texts.append(f"{title} {desc} {loc}")

    # Check each trip against calendar
    for trip in trips:
        trip_words = set()
        for loc in trip["locations"]:
            trip_words.add(loc.lower())
        subj_words = set(re.findall(r"\b\w{4,}\b", trip["subject"].lower()))
        # Remove common words
        subj_words -= {"confirmation", "booking", "your", "reservation", "receipt",
                       "itinerary", "travel", "trip", "email", "from", "with", "order"}
        check_words = trip_words | subj_words

        for cal_text in cal_texts:
            matches = sum(1 for w in check_words if w in cal_text)
            if matches >= 1 and (trip_words & set(cal_text.split())):
                trip["has_calendar_event"] = True
                break
            if matches >= 2:
                trip["has_calendar_event"] = True
                break

    return trips


def _create_events(calendar_svc, trips: list[dict]) -> list[dict]:
    """Create calendar events for trips that don't have one."""
    created = []
    for trip in trips:
        if trip["has_calendar_event"]:
            continue
        if not trip["dates"]:
            continue

        title_parts = []
        type_labels = {"flight": "✈️ Flight", "hotel": "🏨 Hotel", "airbnb": "🏠 Airbnb",
                       "car_rental": "🚗 Car Rental", "train": "🚂 Train", "travel": "✈️ Trip"}
        title_parts.append(type_labels.get(trip["type"], "✈️ Trip"))
        if trip["locations"]:
            title_parts.append(" → ".join(trip["locations"][:2]))

        title = " ".join(title_parts) if len(title_parts) > 1 else title_parts[0]

        # Use first date as start
        start_date = trip["dates"][0]
        end_date = trip["dates"][-1] if len(trip["dates"]) > 1 else start_date

        event_body = {
            "summary": title,
            "description": f"From email: {trip['subject']}\n\n{trip['snippet'][:300]}",
            "start": {"date": start_date},
            "end": {"date": end_date},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 1440},   # 1 day before
                    {"method": "popup", "minutes": 10080},   # 1 week before
                ],
            },
        }

        if trip["locations"]:
            event_body["location"] = ", ".join(trip["locations"][:2])

        try:
            created_ev = calendar_svc.events().insert(
                calendarId="primary", body=event_body,
            ).execute()
            created.append({
                "title": title,
                "start": start_date,
                "end": end_date,
                "locations": trip["locations"],
                "link": created_ev.get("htmlLink", ""),
            })
            trip["has_calendar_event"] = True
        except Exception as e:
            created.append({"title": title, "error": str(e)})

    return created


def execute(args: dict) -> str:
    action = args.get("action", "scan")
    days_ahead = args.get("days_ahead", 90)

    try:
        gmail, calendar_svc = _get_services()
    except Exception as e:
        return json.dumps({"error": f"Auth failed: {e}"})

    if action == "scan":
        try:
            trips = _scan_emails(gmail, days_ahead)
            trips = _check_calendar(calendar_svc, trips, days_ahead)

            # Separate into categories
            with_events = [t for t in trips if t["has_calendar_event"]]
            without_events = [t for t in trips if not t["has_calendar_event"]]

            return json.dumps({
                "action": "scan",
                "total_found": len(trips),
                "on_calendar": len(with_events),
                "missing_from_calendar": len(without_events),
                "trips": trips,
            })
        except Exception as e:
            return json.dumps({"action": "scan", "error": str(e)})

    if action == "create_events":
        try:
            trips = _scan_emails(gmail, days_ahead)
            trips = _check_calendar(calendar_svc, trips, days_ahead)
            created = _create_events(calendar_svc, trips)

            return json.dumps({
                "action": "create_events",
                "created": created,
                "total_trips": len(trips),
                "already_on_calendar": len([t for t in trips if t["has_calendar_event"]]),
            })
        except Exception as e:
            return json.dumps({"action": "create_events", "error": str(e)})

    return json.dumps({"error": f"Unknown action: {action}"})
