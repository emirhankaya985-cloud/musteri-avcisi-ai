"""Public-date-only fail-closed throttle for repeated owner scan error alerts.

No secrets, exception details, customer data or recipient information are stored.
Write attempt state BEFORE contacting Telegram: an ambiguous API result is not
silently retried each following hour. GitHub workflow commits this date only.
"""
import json
import re
from pathlib import Path


def alerted_today(path, day):
    if not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", str(day)):
        raise ValueError("Invalid local day")
    path = Path(path)
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or set(state) != {"alert_attempt_day"}:
            return True  # corrupted state: fail closed, avoid repeated spam
        return state["alert_attempt_day"] == day
    except (OSError, ValueError, TypeError):
        return True


def mark_attempt(path, day):
    if not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", str(day)):
        raise ValueError("Invalid local day")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"alert_attempt_day": day}) + "\n", encoding="utf-8")
    tmp.replace(path)
