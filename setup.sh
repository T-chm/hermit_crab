#!/bin/bash
# Hermit Crab - Setup Script
# Installs all dependencies for the voice assistant

set -e

# Navigate to script directory
cd "$(dirname "$0")"

echo "=== Hermit Crab Setup ==="
echo ""

# --- 1. Check Python ---
install_python() {
    echo "[!] Python 3.10+ is required. Installing via Homebrew..."
    if ! command -v brew &>/dev/null; then
        echo "[!] Homebrew not found. Installing Homebrew first..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
    fi
    brew install python@3.12
    export PATH="$(brew --prefix python@3.12)/libexec/bin:$(brew --prefix)/bin:$PATH"
}

if ! command -v python3 &>/dev/null; then
    install_python
fi
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MINOR" -lt 10 ]; then
    echo "[!] Found $(python3 --version), but 3.10+ is required."
    install_python
fi
echo "[OK] Python: $(python3 --version)"

# --- 2. Check ffmpeg (required by whisper and pydub) ---
if ! command -v ffmpeg &>/dev/null; then
    echo "[!] ffmpeg not found. Installing via Homebrew..."
    if ! command -v brew &>/dev/null; then
        echo "ERROR: Homebrew not found. Install ffmpeg manually:"
        echo "  https://ffmpeg.org/download.html"
        exit 1
    fi
    brew install ffmpeg
else
    echo "[OK] ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
fi

# --- 3. Check Ollama ---
if ! command -v ollama &>/dev/null; then
    echo "[!] Ollama not found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "[OK] Ollama: $(ollama --version 2>&1)"
fi

# --- 4. Create virtual environment and install packages ---
echo ""
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate
echo "[OK] venv: .venv ($(python3 --version))"
echo "Installing Python dependencies..."
pip install -r requirements.txt

# --- 5. Pull the LLM model ---
echo ""
echo "Pulling Qwen 3.5 (4B) model for Ollama..."
echo "This may take a few minutes on first run (~3.4 GB download)."
ollama pull qwen3.5:4b

# --- 6. Verify ---
echo ""
echo "Verifying imports..."
python3 -c "
import fastapi, uvicorn, httpx, whisper, pydub, numpy
print('[OK] All Python packages installed successfully')
"

echo ""
echo "=== Setup complete ==="
echo ""
echo "To run Hermit Crab:"
echo "  1. Start Ollama (if not running):  ollama serve"
echo "  2. Start the app:                  ./run.sh"
echo "  3. Open browser:                   http://localhost:8765"
