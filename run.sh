#!/bin/bash
# Hermit Crab - Run Script
cd "$(dirname "$0")"

# Start Ollama if not already running
if ! pgrep -x ollama &>/dev/null; then
    echo "Starting Ollama..."
    ollama serve &
    sleep 2
fi

source .venv/bin/activate
python3 app.py
