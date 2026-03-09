"""Summarize — summarize URLs, files, and YouTube videos via summarize CLI."""

import shutil
import subprocess

HAS_SUMMARIZE = shutil.which("summarize") is not None

DEFINITION = {
    "type": "function",
    "function": {
        "name": "summarize",
        "description": (
            "Summarize web pages, articles, PDFs, or YouTube videos. "
            "ONLY use when the user explicitly asks to summarize content "
            "from a URL, file, or video. Do NOT call for general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of web page, article, or YouTube video to summarize",
                },
                "length": {
                    "type": "string",
                    "enum": ["short", "medium", "long"],
                    "description": "Summary length. Default: medium",
                },
            },
            "required": ["url"],
        },
    },
}


def execute(args: dict) -> str:
    if not HAS_SUMMARIZE:
        return (
            "summarize CLI is not installed. "
            "Install with: brew install steipete/tap/summarize"
        )

    url = args.get("url", "")
    length = args.get("length", "medium")

    if not url:
        return "Please provide a URL or file path to summarize."

    cmd = ["summarize", url, "--length", length]

    # Auto-detect YouTube URLs
    if "youtube.com" in url or "youtu.be" in url:
        cmd += ["--youtube", "auto"]

    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return f"Could not summarize: {r.stderr.strip()}"
        return r.stdout.strip() or "No summary generated."
    except subprocess.TimeoutExpired:
        return "Summarization timed out (content may be too large)."
    except Exception as e:
        return f"Summarize error: {e}"
