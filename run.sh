#!/bin/bash
# Hermit Crab - Run Script
cd "$(dirname "$0")"
source .venv/bin/activate
python3 app.py
