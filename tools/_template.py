"""
Tool Template for Hermit Crab
==============================
To create a new tool:

1. Copy this file to tools/your_tool_name.py (no leading underscore)
2. Fill in DEFINITION with your tool's Ollama schema
3. Implement the execute() function
4. Restart the server — the tool is auto-discovered

The file MUST export:
  DEFINITION  - dict matching Ollama's tool calling schema
  execute     - function(args: dict) -> str
"""

DEFINITION = {
    "type": "function",
    "function": {
        "name": "your_tool_name",
        "description": (
            "What this tool does. Be specific so the LLM knows when to use it. "
            "Include when NOT to use it to prevent false triggers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["action_a", "action_b"],
                    "description": "action_a: does X. action_b: does Y.",
                },
                "query": {
                    "type": "string",
                    "description": "A search term or input value",
                },
            },
            "required": ["action"],
        },
    },
}


def execute(args: dict) -> str:
    """Execute the tool. Returns a string result for the LLM."""
    action = args.get("action", "")

    if action == "action_a":
        query = args.get("query", "")
        # Your logic here
        return f"Did action_a with: {query}"

    elif action == "action_b":
        return "Did action_b"

    return f"Unknown action: {action}"
