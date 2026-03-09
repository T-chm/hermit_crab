"""Apple Reminders — manage reminders via remindctl CLI (macOS)."""

import shutil
import subprocess

HAS_REMINDCTL = shutil.which("remindctl") is not None

DEFINITION = {
    "type": "function",
    "function": {
        "name": "reminders",
        "description": (
            "Create, view, and complete Apple Reminders on macOS. "
            "ONLY use when the user explicitly asks to create a reminder, "
            "check their reminders, or mark tasks as done. "
            "Do NOT call for general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "today", "tomorrow", "week", "overdue", "all",
                        "add", "complete", "list_lists",
                    ],
                    "description": (
                        "today/tomorrow/week/overdue/all: view reminders for that period. "
                        "add: create a new reminder (set title, optionally due and list). "
                        "complete: mark reminder(s) as done (set query to reminder ID). "
                        "list_lists: show all reminder lists."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Title for a new reminder (used with 'add')",
                },
                "due": {
                    "type": "string",
                    "description": "Due date: 'today', 'tomorrow', or 'YYYY-MM-DD HH:MM' (used with 'add')",
                },
                "list": {
                    "type": "string",
                    "description": "Which reminder list to use (e.g. 'Personal', 'Work')",
                },
                "query": {
                    "type": "string",
                    "description": "Reminder ID(s) to complete (space-separated)",
                },
            },
            "required": ["action"],
        },
    },
}


def _remindctl(args: list, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["remindctl"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return f"Error: {r.stderr.strip()}"
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: remindctl command timed out"
    except Exception as e:
        return f"Error: {e}"


def execute(args: dict) -> str:
    if not HAS_REMINDCTL:
        return (
            "remindctl is not installed. "
            "Install with: brew install steipete/tap/remindctl"
        )

    action = args.get("action", "")
    title = args.get("title", "")
    due = args.get("due", "")
    lst = args.get("list", "")
    query = args.get("query", "")

    if action in ("today", "tomorrow", "week", "overdue", "all"):
        cmd = [action]
        if lst:
            cmd = ["list", lst]
        result = _remindctl(cmd)
        return result or f"No reminders for '{action}'."

    elif action == "add":
        if not title:
            return "Please specify what to remind you about."
        cmd = ["add", "--title", title]
        if due:
            cmd += ["--due", due]
        if lst:
            cmd += ["--list", lst]
        result = _remindctl(cmd)
        if result.startswith("Error"):
            return result
        msg = f"Reminder created: {title}"
        if due:
            msg += f" (due: {due})"
        return msg

    elif action == "complete":
        if not query:
            return "Please specify the reminder ID(s) to complete."
        ids = query.split()
        result = _remindctl(["complete"] + ids)
        if result.startswith("Error"):
            return result
        return f"Completed reminder(s): {query}"

    elif action == "list_lists":
        return _remindctl(["list"]) or "No reminder lists found."

    return f"Unknown action: {action}"
