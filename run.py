#!/usr/bin/env python3
"""Render startup wrapper for Vera bot."""
import os
import sys
import subprocess

port = os.environ.get("PORT", "8080")
host = "0.0.0.0"

print(f"Starting Vera bot on {host}:{port}...")
sys.stdout.flush()

try:
    subprocess.run(
        ["uvicorn", "bot:app", "--host", host, "--port", port, "--log-level", "info"],
        check=True
    )
except Exception as e:
    print(f"Failed to start bot: {e}", file=sys.stderr)
    sys.exit(1)
