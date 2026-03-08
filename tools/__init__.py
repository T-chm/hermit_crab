"""
Hermit Crab - Tool Plugin Loader

Auto-discovers tool modules in this directory.
Each module must export:
  DEFINITION  - dict matching Ollama's tool calling schema
  execute     - function(args: dict) -> str
"""

import importlib
from pathlib import Path

TOOLS = []
EXECUTORS = {}

_dir = Path(__file__).parent
for _f in sorted(_dir.glob("*.py")):
    if _f.name.startswith("_"):
        continue
    try:
        _mod = importlib.import_module(f".{_f.stem}", package=__name__)
    except Exception as e:
        print(f"[tools] Failed to load {_f.name}: {e}")
        continue
    _defn = getattr(_mod, "DEFINITION", None)
    _func = getattr(_mod, "execute", None)
    if _defn and _func:
        TOOLS.append(_defn)
        EXECUTORS[_defn["function"]["name"]] = _func


def execute_tool(name: str, args: dict) -> str:
    fn = EXECUTORS.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    return fn(args)
