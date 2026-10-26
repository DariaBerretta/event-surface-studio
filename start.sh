#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required."
    exit 1
fi
if [ ! -d .venv ]; then
    echo "Creating isolated Python environment for the GUI..."
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import streamlit, PIL' 2>/dev/null; then
    echo "Installing Streamlit and Pillow..."
    .venv/bin/python -m pip install -r requirements.txt
fi
printf '\nOpen Event Surface Studio in your browser: http://localhost:8501\n'
exec .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
