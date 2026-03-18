"""Browser — web browsing and information extraction via page-agent extension."""

import asyncio

DEFINITION = {
    "type": "function",
    "function": {
        "name": "browser",
        "description": (
            "Browse the web using a real browser. Navigate to URLs, extract page "
            "content, search for information, or interact with web pages. "
            "Powered by the page-agent browser extension. "
            "Use for property lookups, web research, or any task needing live web data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "Natural language description of what to do in the browser. "
                        "Examples: 'Go to zillow.com and search for 456 Maple Drive', "
                        "'Extract the price and details from this property listing', "
                        "'Search Google for average home prices in Austin TX 2026'."
                    ),
                },
            },
            "required": ["task"],
        },
    },
}


def execute(args: dict) -> str:
    task = args.get("task", "")
    if not task:
        return "Please specify a browsing task."

    # execute() runs in a thread via asyncio.to_thread() in app.py.
    # We need to send the task to the bridge WS on the main event loop.
    try:
        from app import send_browser_task
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in a thread — schedule coroutine on the running loop
            future = asyncio.run_coroutine_threadsafe(
                send_browser_task(task), loop
            )
            return future.result(timeout=130)
        else:
            return asyncio.run(send_browser_task(task))
    except ImportError:
        return "Browser bridge not available (app module not loaded)."
    except TimeoutError:
        return "Browser task timed out."
    except Exception as e:
        return f"Browser error: {e}"
