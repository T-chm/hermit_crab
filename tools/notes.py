"""Apple Notes — create, search, and list notes (macOS)."""

import subprocess

DEFINITION = {
    "type": "function",
    "function": {
        "name": "notes",
        "description": (
            "Create, search, and list Apple Notes on macOS. "
            "ONLY use when the user explicitly asks to take a note, "
            "find notes, or list their notes. "
            "Do NOT call for general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "search", "create"],
                    "description": (
                        "list: show all notes (optionally filter by folder). "
                        "search: search notes by keyword. "
                        "create: create a new note (set title and optionally body)."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "Search term (for 'search') or folder name (for 'list')",
                },
                "title": {
                    "type": "string",
                    "description": "Title for a new note (used with 'create')",
                },
                "body": {
                    "type": "string",
                    "description": "Content body for a new note (used with 'create')",
                },
            },
            "required": ["action"],
        },
    },
}


def _applescript(script: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return f"Error: {r.stderr.strip()}"
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: AppleScript timed out"
    except Exception as e:
        return f"Error: {e}"


def execute(args: dict) -> str:
    action = args.get("action", "")
    query = args.get("query", "")
    title = args.get("title", "")
    body = args.get("body", "")

    if action == "list":
        if query:
            safe_folder = query.replace('"', '\\"')
            result = _applescript(
                f'tell application "Notes"\n'
                f'  set output to ""\n'
                f'  try\n'
                f'    set theFolder to folder "{safe_folder}"\n'
                f'    repeat with n in notes of theFolder\n'
                f'      set output to output & name of n & linefeed\n'
                f'    end repeat\n'
                f'  on error\n'
                f'    return "Folder not found: {safe_folder}"\n'
                f'  end try\n'
                f'  return output\n'
                f'end tell',
                timeout=15,
            )
        else:
            result = _applescript(
                'tell application "Notes"\n'
                '  set output to ""\n'
                '  set noteList to every note\n'
                '  set maxShow to 30\n'
                '  if (count of noteList) < maxShow then set maxShow to (count of noteList)\n'
                '  repeat with i from 1 to maxShow\n'
                '    set n to item i of noteList\n'
                '    set output to output & name of n & linefeed\n'
                '  end repeat\n'
                '  if (count of noteList) > 30 then\n'
                '    set output to output & "... and " & ((count of noteList) - 30) & " more notes"\n'
                '  end if\n'
                '  return output\n'
                'end tell',
                timeout=15,
            )
        return result or "No notes found."

    elif action == "search":
        if not query:
            return "Please specify a search term."
        safe_query = query.replace('"', '\\"')
        result = _applescript(
            f'tell application "Notes"\n'
            f'  set output to ""\n'
            f'  set matches to (every note whose name contains "{safe_query}")\n'
            f'  repeat with n in matches\n'
            f'    set output to output & name of n & linefeed\n'
            f'  end repeat\n'
            f'  if output is "" then return "No notes matching \\"{safe_query}\\""\n'
            f'  return output\n'
            f'end tell',
            timeout=15,
        )
        return result

    elif action == "create":
        if not title:
            return "Please specify a title for the note."
        safe_title = title.replace('"', '\\"')
        if body:
            safe_body = body.replace('"', '\\"').replace('\n', '<br>')
            script = (
                f'tell application "Notes"\n'
                f'  make new note at folder "Notes" with properties '
                f'{{name:"{safe_title}", body:"{safe_title}<br>{safe_body}"}}\n'
                f'end tell'
            )
        else:
            script = (
                f'tell application "Notes"\n'
                f'  make new note at folder "Notes" with properties '
                f'{{name:"{safe_title}"}}\n'
                f'end tell'
            )
        result = _applescript(script)
        if result.startswith("Error"):
            return f"Could not create note: {result}"
        return f"Note created: {title}"

    return f"Unknown action: {action}"
