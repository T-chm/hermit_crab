"""Gmail — read, send, and triage emails via Google API Python client."""

import base64
import json
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from ._google_auth import get_credentials

DEFINITION = {
    "type": "function",
    "function": {
        "name": "gmail",
        "description": (
            "Access Gmail: read emails, send emails, check unread, search inbox. "
            "ONLY use when the user explicitly asks about email, inbox, or sending messages via email."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["unread", "search", "read", "send"],
                    "description": (
                        "unread: list recent unread emails. "
                        "search: search emails by query. "
                        "read: read a specific email by ID. "
                        "send: send an email."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "Search query for 'search' action (Gmail search syntax).",
                },
                "message_id": {
                    "type": "string",
                    "description": "Message ID for 'read' action.",
                },
                "to": {
                    "type": "string",
                    "description": "Recipient email address for 'send' action.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject for 'send' action.",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text for 'send' action.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5).",
                },
            },
            "required": ["action"],
        },
    },
}


def _get_service():
    creds = get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _extract_headers(headers: list, *names: str) -> dict:
    """Extract specific headers by name (case-insensitive)."""
    want = {n.lower() for n in names}
    result = {}
    for h in headers:
        if h["name"].lower() in want:
            result[h["name"].lower()] = h["value"]
    return result


def _extract_body(payload: dict) -> str:
    """Extract plain text body from message payload."""
    # Direct body
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart — find text/plain
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        # Nested multipart
        for sub in part.get("parts", []):
            if sub.get("mimeType") == "text/plain" and sub.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(sub["body"]["data"]).decode("utf-8", errors="replace")
    return ""


def _fetch_message_meta(service, msg_id: str) -> dict:
    """Fetch message metadata (headers + snippet)."""
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="metadata",
        metadataHeaders=["From", "Subject", "Date"],
    ).execute()
    headers = _extract_headers(msg.get("payload", {}).get("headers", []), "from", "subject", "date")
    return {
        "id": msg.get("id", ""),
        "from": headers.get("from", "Unknown"),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "labels": msg.get("labelIds", []),
    }


def _list_emails(service, query: str, max_results: int) -> tuple[int, list[dict]]:
    """List emails matching query, return (total_estimate, email_list)."""
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=max_results,
    ).execute()

    total = resp.get("resultSizeEstimate", 0)
    messages = resp.get("messages", [])

    results = []
    for msg in messages[:max_results]:
        try:
            info = _fetch_message_meta(service, msg["id"])
            results.append(info)
        except Exception:
            results.append({"id": msg.get("id", ""), "snippet": "(could not load)"})

    return total, results


def execute(args: dict) -> str:
    action = args.get("action", "unread")
    max_results = args.get("max_results", 5)

    try:
        service = _get_service()
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Auth failed: {e}. Try deleting ~/.hermit_crab/google_token.json and retry."})

    if action == "unread":
        try:
            total, emails = _list_emails(service, "is:unread", max_results)
            return json.dumps({"action": "unread", "total": total, "emails": emails})
        except Exception as e:
            return json.dumps({"action": "unread", "error": str(e)})

    if action == "search":
        query = args.get("query", "")
        if not query:
            return json.dumps({"action": "search", "error": "Please specify a search query."})
        try:
            total, emails = _list_emails(service, query, max_results)
            return json.dumps({"action": "search", "query": query, "total": total, "emails": emails})
        except Exception as e:
            return json.dumps({"action": "search", "error": str(e)})

    if action == "read":
        msg_id = args.get("message_id", "")
        if not msg_id:
            return json.dumps({"action": "read", "error": "Please specify a message ID."})
        try:
            msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            payload = msg.get("payload", {})
            headers = _extract_headers(payload.get("headers", []), "from", "to", "subject", "date")
            body = _extract_body(payload)
            return json.dumps({"action": "read", "email": {
                "id": msg.get("id", ""),
                "from": headers.get("from", "Unknown"),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "snippet": msg.get("snippet", ""),
                "body": body[:1500] if body else msg.get("snippet", ""),
                "labels": msg.get("labelIds", []),
            }})
        except Exception as e:
            return json.dumps({"action": "read", "error": str(e)})

    if action == "send":
        to = args.get("to", "")
        subject = args.get("subject", "")
        body = args.get("body", "")
        if not to:
            return json.dumps({"action": "send", "error": "Please specify a recipient."})
        if not subject and not body:
            return json.dumps({"action": "send", "error": "Please specify a subject or body."})
        try:
            message = MIMEText(body or "")
            message["to"] = to
            message["subject"] = subject or "(no subject)"
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return json.dumps({"action": "send", "to": to, "subject": subject, "status": "sent"})
        except Exception as e:
            return json.dumps({"action": "send", "error": str(e)})

    return json.dumps({"error": f"Unknown action: {action}"})
