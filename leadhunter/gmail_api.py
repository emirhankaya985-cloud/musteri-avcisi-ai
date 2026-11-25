"""Optional Gmail API transport using an owner-authorized OAuth refresh token.

This adapter is deliberately not wired into either production mail worker.
It is disabled unless an operator explicitly enables it, and callers must
retain the existing recipient eligibility, idempotency, and reputation gates.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from email.utils import formataddr
import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}\Z"
)


def _credentials(env):
    if not hasattr(env, "get"):
        raise RuntimeError("Gmail API configuration invalid")
    if env.get("GMAIL_API_ENABLED") != "true":
        raise RuntimeError("Gmail API sender disabled")
    sender = str(env.get("GMAIL_SENDER_ADDRESS") or "").strip()
    if not _EMAIL.fullmatch(sender):
        raise RuntimeError("Gmail API sender address invalid")
    if env.get("GMAIL_OAUTH_SCOPE") != SCOPE:
        raise RuntimeError("Gmail API OAuth scope must be gmail.send")
    keys = ("GMAIL_OAUTH_CLIENT_ID", "GMAIL_OAUTH_CLIENT_SECRET",
            "GMAIL_OAUTH_REFRESH_TOKEN")
    values = {key: str(env.get(key) or "") for key in keys}
    if any(not value.strip() for value in values.values()):
        raise RuntimeError("Gmail API OAuth credentials are incomplete")
    return sender, values


def _read_json(response):
    try:
        result = json.load(response)
    except Exception:
        raise RuntimeError("Gmail API returned an invalid response") from None
    if not isinstance(result, dict):
        raise RuntimeError("Gmail API returned an invalid response")
    return result


def _refresh_access_token(credentials, opener):
    payload = urlencode({
        "client_id": credentials["GMAIL_OAUTH_CLIENT_ID"],
        "client_secret": credentials["GMAIL_OAUTH_CLIENT_SECRET"],
        "refresh_token": credentials["GMAIL_OAUTH_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode("ascii")
    request = Request(TOKEN_URL, data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }, method="POST")
    try:
        with opener(request, timeout=30) as response:
            result = _read_json(response)
    except HTTPError:
        raise RuntimeError("Gmail OAuth token refresh failed; details redacted") from None
    except Exception:
        raise RuntimeError("Gmail OAuth token refresh failed; details redacted") from None
    token = result.get("access_token")
    if (not isinstance(token, str) or not token.strip()
            or result.get("token_type", "Bearer").casefold() != "bearer"):
        raise RuntimeError("Gmail OAuth response omitted a valid bearer token")
    return token


def _message(sender, recipient, subject, body):
    if not isinstance(recipient, str) or not _EMAIL.fullmatch(recipient.strip()):
        raise ValueError("Recipient address invalid")
    if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= 150:
        raise ValueError("Subject invalid")
    if not isinstance(body, str) or not 1 <= len(body) <= 12000:
        raise ValueError("Message body invalid")
    if "\r" in subject or "\n" in subject or "\x00" in body:
        raise ValueError("Message headers or body invalid")
    msg = EmailMessage()
    msg["From"] = formataddr(("Müşteri Avcısı AI", sender))
    msg["To"] = recipient.strip()
    msg["Subject"] = subject.strip()
    msg.set_content(body)
    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")
    return {"raw": encoded}


def send_message(recipient, subject, body, env=None, opener=urlopen):
    """Send through Gmail API and return its actual immutable message ID.

    This adapter is not connected to scheduled outreach. Even when explicitly
    enabled, its caller remains responsible for legal eligibility, duplicate
    claims, quota, and the reputation circuit before calling this low-level
    transport.
    """
    env = os.environ if env is None else env
    sender, credentials = _credentials(env)
    payload = _message(sender, recipient, subject, body)
    access_token = _refresh_access_token(credentials, opener)
    request = Request(SEND_URL, data=json.dumps(payload).encode("ascii"),
                      headers={
                          "Authorization": "Bearer " + access_token,
                          "Content-Type": "application/json",
                          "Accept": "application/json",
                      }, method="POST")
    try:
        with opener(request, timeout=30) as response:
            result = _read_json(response)
    except HTTPError:
        raise RuntimeError("Gmail API send failed; details redacted") from None
    except Exception:
        raise RuntimeError("Gmail API send failed; details redacted") from None
    message_id = result.get("id")
    if not isinstance(message_id, str) or not message_id.strip():
        raise RuntimeError("Gmail API accepted no verifiable message ID")
    return message_id
