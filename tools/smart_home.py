"""Smart home — Philips Hue light control via openhue CLI."""

import shutil
import subprocess

HAS_OPENHUE = shutil.which("openhue") is not None

DEFINITION = {
    "type": "function",
    "function": {
        "name": "smart_home",
        "description": (
            "Control Philips Hue smart lights, rooms, and scenes. "
            "ONLY use when the user explicitly asks to control lights "
            "(turn on/off, brightness, color, scenes). "
            "Do NOT call for general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_lights", "list_rooms", "list_scenes",
                        "turn_on", "turn_off", "set_brightness", "set_color",
                        "set_scene",
                    ],
                    "description": (
                        "list_lights: show all lights and status. "
                        "list_rooms: show all rooms. "
                        "list_scenes: show available scenes. "
                        "turn_on/turn_off: switch a light or room on/off. "
                        "set_brightness: set brightness 0-100. "
                        "set_color: set light color. "
                        "set_scene: activate a scene in a room."
                    ),
                },
                "target": {
                    "type": "string",
                    "description": "Name of the light, room, or scene (e.g. 'Bedroom Lamp', 'Living Room')",
                },
                "value": {
                    "type": "string",
                    "description": "Brightness (0-100) or color name/hex (e.g. 'red', '#FF5500')",
                },
                "room": {
                    "type": "string",
                    "description": "Room name — used with set_scene to specify which room",
                },
            },
            "required": ["action"],
        },
    },
}


def _openhue(args: list, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["openhue"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return f"Error: {r.stderr.strip()}"
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: openhue command timed out"
    except Exception as e:
        return f"Error: {e}"


def execute(args: dict) -> str:
    if not HAS_OPENHUE:
        return (
            "openhue CLI is not installed. "
            "Install with: brew install openhue/cli/openhue-cli"
        )

    action = args.get("action", "")
    target = args.get("target", "")
    value = args.get("value", "")
    room = args.get("room", "")

    if action == "list_lights":
        return _openhue(["get", "light"]) or "No lights found."

    elif action == "list_rooms":
        return _openhue(["get", "room"]) or "No rooms found."

    elif action == "list_scenes":
        return _openhue(["get", "scene"]) or "No scenes found."

    elif action == "turn_on":
        if not target:
            return "Please specify which light or room to turn on."
        result = _openhue(["set", "light", target, "--on"])
        if result.startswith("Error"):
            result = _openhue(["set", "room", target, "--on"])
        return result if not result.startswith("Error") else f"Could not turn on '{target}'. {result}"

    elif action == "turn_off":
        if not target:
            return "Please specify which light or room to turn off."
        result = _openhue(["set", "light", target, "--off"])
        if result.startswith("Error"):
            result = _openhue(["set", "room", target, "--off"])
        return result if not result.startswith("Error") else f"Could not turn off '{target}'. {result}"

    elif action == "set_brightness":
        if not target:
            return "Please specify which light."
        if not value:
            return "Please specify a brightness level (0-100)."
        return _openhue(["set", "light", target, "--on", "--brightness", value])

    elif action == "set_color":
        if not target:
            return "Please specify which light."
        if not value:
            return "Please specify a color."
        if value.startswith("#"):
            return _openhue(["set", "light", target, "--on", "--rgb", value])
        return _openhue(["set", "light", target, "--on", "--color", value])

    elif action == "set_scene":
        if not target:
            return "Please specify a scene name."
        cmd = ["set", "scene", target]
        if room:
            cmd += ["--room", room]
        return _openhue(cmd)

    return f"Unknown action: {action}"
