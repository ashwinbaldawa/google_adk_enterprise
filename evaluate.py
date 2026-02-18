"""
Entry point: Run evaluation pipeline.

Usage:
    python evaluate.py
    python evaluate.py --session-id <id>
    python evaluate.py --limit 100
"""

import argparse
import asyncio

from dotenv import load_dotenv

load_dotenv()

from src.evaluation import run_evaluation


def main():
    parser = argparse.ArgumentParser(description="Evaluate agent responses")
    parser.add_argument("--session-id", type=str, help="Specific session to evaluate")
    parser.add_argument("--limit", type=int, default=50, help="Max events to fetch")
    args = parser.parse_args()

    asyncio.run(run_evaluation(session_id=args.session_id, limit=args.limit))


if __name__ == "__main__":
    main()
