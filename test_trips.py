"""Diagnostic test for trips tool — shows what emails are found and why they're kept/dropped."""

import json
import re
from datetime import datetime, timedelta, timezone

from tools._google_auth import get_credentials
from googleapiclient.discovery import build
from tools.trips import (
    _TRAVEL_QUERIES, _NOISE_PATTERNS, _DATE_PATTERNS, _DATE_FORMATS,
    _extract_dates, _detect_type, _extract_locations, _is_noise,
    _extract_body_text,
)


def main():
    print("=" * 70)
    print("TRIPS TOOL DIAGNOSTIC")
    print("=" * 70)

    creds = get_credentials()
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)

    now = datetime.now(timezone.utc)
    today = now.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    after_date = now - timedelta(days=180)
    after_str = after_date.strftime("%Y/%m/%d")

    print(f"\nToday: {today.strftime('%Y-%m-%d')}")
    print(f"Searching emails after: {after_str}")
    print(f"Looking for trips with dates >= {today.strftime('%Y-%m-%d')}")

    # Step 1: Run each query and show results
    all_msg_ids = set()
    all_messages = []

    for i, query in enumerate(_TRAVEL_QUERIES):
        full_query = f"({query}) after:{after_str}"
        try:
            resp = gmail.users().messages().list(
                userId="me", q=full_query, maxResults=10,
            ).execute()
            msgs = resp.get("messages", [])
            print(f"\n--- Query {i+1}: {query[:80]}...")
            print(f"    Found: {len(msgs)} emails")
            for msg in msgs:
                if msg["id"] not in all_msg_ids:
                    all_msg_ids.add(msg["id"])
                    all_messages.append(msg)
        except Exception as e:
            print(f"\n--- Query {i+1}: ERROR: {e}")

    print(f"\n{'=' * 70}")
    print(f"Total unique emails found: {len(all_messages)}")
    print(f"{'=' * 70}")

    # Step 2: Process each email and show filtering decisions
    for idx, msg in enumerate(all_messages[:20]):
        try:
            detail = gmail.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()

            headers = {}
            for h in detail.get("payload", {}).get("headers", []):
                headers[h["name"].lower()] = h["value"]

            subject = headers.get("subject", "")
            snippet = detail.get("snippet", "")
            full_text = f"{subject} {snippet}"
            email_date = headers.get("date", "")

            print(f"\n{'─' * 70}")
            print(f"Email {idx+1}: {subject[:80]}")
            print(f"  From: {headers.get('from', '?')[:60]}")
            print(f"  Date: {email_date[:40]}")
            print(f"  Snippet: {snippet[:120]}...")

            # Check noise
            is_noise = _is_noise(subject, snippet)
            if is_noise:
                print(f"  ❌ FILTERED: noise (policy/marketing/survey)")
                continue

            # Extract dates
            dates = _extract_dates(full_text)
            print(f"  Dates found: {[d.strftime('%Y-%m-%d') for d in dates] if dates else 'NONE'}")

            # Check future dates
            future_dates = [d for d in dates if d >= today]
            print(f"  Future dates: {[d.strftime('%Y-%m-%d') for d in future_dates] if future_dates else 'NONE'}")

            # If no dates from snippet, try full body
            body_text = ""
            if not dates:
                print(f"  No dates in snippet — fetching full body...")
                try:
                    full_detail = gmail.users().messages().get(
                        userId="me", id=msg["id"], format="full",
                    ).execute()
                    body_text = _extract_body_text(full_detail.get("payload", {}))
                    dates = _extract_dates(f"{subject} {body_text}")
                    full_text = f"{subject} {body_text}"
                    print(f"  Body length: {len(body_text)} chars")
                    print(f"  Dates from body: {[d.strftime('%Y-%m-%d') for d in dates] if dates else 'NONE'}")
                except Exception as e:
                    print(f"  Body fetch error: {e}")

            future_dates = [d for d in dates if d >= today]
            print(f"  Future dates: {[d.strftime('%Y-%m-%d') for d in future_dates] if future_dates else 'NONE'}")

            if not future_dates:
                print(f"  ❌ FILTERED: no future dates")
                if dates:
                    for d in dates:
                        delta = (today - d).days
                        print(f"     → {d.strftime('%Y-%m-%d')} was {delta} days ago")
                else:
                    print(f"     → No date patterns matched anywhere")
                continue

            # Type and locations
            trip_type = _detect_type(full_text)
            locations = _extract_locations(f"{subject} {snippet}")
            print(f"  Type: {trip_type}")
            print(f"  Locations: {locations}")
            print(f"  ✅ KEPT — upcoming {trip_type}")

        except Exception as e:
            print(f"\n  ERROR processing email: {e}")

    print(f"\n{'=' * 70}")
    print("DONE")


if __name__ == "__main__":
    main()
