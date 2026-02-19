"""
Entry point: Launch evaluation dashboard.

Usage:
    python serve.py
    # Open http://localhost:8050
"""

import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from src.api import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8050"))
    print(f"\n🚀 Dashboard: http://localhost:{port}")
    print(f"   API docs:  http://localhost:{port}/docs")
    print(f"   Press Ctrl+C to stop\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
