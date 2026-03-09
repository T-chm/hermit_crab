"""iMessage — send and read messages via imsg CLI (macOS)."""

import json as _json
import shutil
import subprocess

HAS_IMSG = shutil.which("imsg") is not None

DEFINITION = {
    "type": "function",
    "function": {
        "name": "messaging",
        "description": (
            "Send and read iMessages or SMS on macOS. "
            "ONLY use when the user explicitly asks to send a text, "
            "read messages, or check conversations. "
            "Do NOT call for general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send", "list_chats", "read_chat"],
                    "description": (
                        "send: send a message to a contact. "
                        "list_chats: show recent conversations. "
                        "read_chat: read recent messages from a conversation."
                    ),
                },
                "to": {
                    "type": "string",
                    "description": "Phone number or contact to send to (with 'send')",
                },
                "text": {
                    "type": "string",
                    "description": "Message text to send",
                },
                "chat_id": {
                    "type": "string",
                    "description": "Chat ID to read (from list_chats output)",
                },
            },
            "required": ["action"],
        },
    },
}


def _imsg(args: list, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["imsg"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return f"Error: {r.stderr.strip()}"
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: imsg command timed out"
    except Exception as e:
        return f"Error: {e}"


def execute(args: dict) -> str:
    if not HAS_IMSG:
        return (
            "imsg CLI is not installed. "
            "Install with: brew install steipete/tap/imsg "
            "(requires Full Disk Access for your terminal)"
        )

    action = args.get("action", "")

    if action == "list_chats":
        result = _imsg(["chats", "--limit", "10", "--json"])
        if result.startswith("Error"):
            return result
        try:
            chats = _json.loads(result)
            if not chats:
                return "No recent conversations found."
            lines = ["Recent conversations:"]
            for c in chats:
                name = c.get("display_name") or c.get("chat_identifier", "Unknown")
                chat_id = c.get("chat_id", "?")
                lines.append(f"  [{chat_id}] {name}")
            return "\n".join(lines)
        except (_json.JSONDecodeError, ValueError):
            return result

    elif action == "read_chat":
        chat_id = args.get("chat_id", "")
        if not chat_id:
            return "Please specify a chat_id. Use list_chats to see conversations."
        result = _imsg(["history", "--chat-id", chat_id, "--limit", "20", "--json"])
        if result.startswith("Error"):
            return result
        try:
            messages = _json.loads(result)
            if not messages:
                return "No messages found in this chat."
            lines = []
            for m in messages:
                sender = "You" if m.get("is_from_me") else m.get("sender", "Them")
                text = m.get("text", "")
                lines.append(f"  {sender}: {text}")
            return "\n".join(lines)
        except (_json.JSONDecodeError, ValueError):
            return result

    elif action == "send":
        to = args.get("to", "")
        text = args.get("text", "")
        if not to:
            return "Please specify who to send the message to."
        if not text:
            return "Please specify the message text."
        result = _imsg(["send", "--to", to, "--text", text])
        if result.startswith("Error"):
            return result
        return f"Message sent to {to}."

    return f"Unknown action: {action}"
