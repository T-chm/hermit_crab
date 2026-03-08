#!/usr/bin/env python3
"""
Whisper + Ollama Integration
- Records audio from microphone (or reads an audio file)
- Transcribes speech to text with OpenAI Whisper
- Sends the transcription to a local Ollama LLM for processing
"""

import argparse
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import requests
import scipy.io.wavfile as wavfile
import sounddevice as sd
import whisper

warnings.filterwarnings("ignore", category=FutureWarning)

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2"
DEFAULT_WHISPER_MODEL = "base"
SAMPLE_RATE = 16000


def record_audio(duration: int) -> np.ndarray:
    """Record audio from the default microphone."""
    print(f"Recording for {duration} seconds... Speak now!")
    audio = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    print("Recording complete.")
    return audio.flatten()


def transcribe(audio_path: str, model_name: str = DEFAULT_WHISPER_MODEL) -> str:
    """Transcribe audio file using Whisper."""
    print(f"Loading Whisper model '{model_name}'...")
    model = whisper.load_model(model_name)
    print("Transcribing...")
    result = model.transcribe(audio_path)
    return result["text"].strip()


def query_ollama(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str = "You are a helpful assistant. Respond to the user's spoken input.",
) -> str:
    """Send a prompt to Ollama and return the response."""
    print(f"Sending to Ollama ({model})...")
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["response"]
    except requests.ConnectionError:
        return "Error: Cannot connect to Ollama. Is it running? (ollama serve)"
    except requests.exceptions.RequestException as e:
        return f"Error communicating with Ollama: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="Whisper speech-to-text + Ollama LLM integration"
    )
    parser.add_argument(
        "-f", "--file", type=str, help="Path to an audio file to transcribe"
    )
    parser.add_argument(
        "-d", "--duration", type=int, default=5, help="Recording duration in seconds (default: 5)"
    )
    parser.add_argument(
        "-w", "--whisper-model",
        type=str,
        default=DEFAULT_WHISPER_MODEL,
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "-m", "--model", type=str, default=DEFAULT_MODEL, help="Ollama model name (default: llama3.2)"
    )
    parser.add_argument(
        "-s", "--system", type=str, default=None, help="Custom system prompt for Ollama"
    )
    parser.add_argument(
        "--transcribe-only", action="store_true", help="Only transcribe, don't send to Ollama"
    )
    parser.add_argument(
        "--loop", action="store_true", help="Continuous conversation mode"
    )
    args = parser.parse_args()

    system_prompt = args.system or "You are a helpful assistant. Respond to the user's spoken input."

    while True:
        # Step 1: Get audio
        if args.file:
            audio_path = args.file
            if not Path(audio_path).exists():
                print(f"Error: File '{audio_path}' not found.")
                sys.exit(1)
        else:
            audio_data = record_audio(args.duration)
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            audio_path = tmp.name
            wavfile.write(audio_path, SAMPLE_RATE, (audio_data * 32767).astype(np.int16))
            tmp.close()

        # Step 2: Transcribe
        text = transcribe(audio_path, args.whisper_model)
        print(f"\n--- Transcription ---\n{text}\n")

        if not text:
            print("(No speech detected)")
            if not args.loop:
                break
            continue

        # Step 3: Send to Ollama
        if not args.transcribe_only:
            response = query_ollama(text, model=args.model, system_prompt=system_prompt)
            print(f"--- Ollama Response ---\n{response}\n")

        if not args.loop or args.file:
            break

        print("--- Press Ctrl+C to stop, or speak again ---\n")


if __name__ == "__main__":
    main()
