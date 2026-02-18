"""Agent tool functions."""

import datetime
from typing import Any


def get_current_time(timezone: str = "UTC") -> dict[str, Any]:
    """Returns the current date and time."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "status": "success",
        "datetime": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
    }


def remember_info(key: str, value: str) -> dict[str, str]:
    """Remembers information by storing it in session state."""
    return {
        "status": "stored",
        "message": f"I'll remember that {key} = {value}",
        "key": key,
        "value": value,
    }


def recall_info(key: str) -> dict[str, str]:
    """Recalls previously stored information from session state."""
    return {
        "status": "recalled",
        "key": key,
        "message": f"Looking up stored information for key: {key}",
    }


def calculate(expression: str) -> dict[str, Any]:
    """Evaluates a simple mathematical expression like '2 + 2' or '15 * 3.14'."""
    try:
        allowed_chars = set("0123456789+-*/.() ")
        if not all(c in allowed_chars for c in expression):
            return {"status": "error", "message": "Only basic math operations allowed."}
        result = eval(expression)
        return {"status": "success", "expression": expression, "result": result}
    except Exception as e:
        return {"status": "error", "expression": expression, "message": str(e)}
