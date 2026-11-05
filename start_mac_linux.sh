#!/usr/bin/env bash
# Startet die App direkt aus dem Quellcode. Benötigt Python 3.10+.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
.venv/bin/python run.py
