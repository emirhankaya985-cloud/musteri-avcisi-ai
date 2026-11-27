"""Read-only Gmail SMTP authentication check. Never sends a message."""
import os
import smtplib
import ssl

from .gmail_selftest import PORT, SERVER, sender_credentials


def check(env=None, smtp_factory=smtplib.SMTP_SSL):
    env = os.environ if env is None else env
    sender, password = sender_credentials(env)
    try:
        with smtp_factory(SERVER, PORT, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.ehlo()
            smtp.login(sender, password)
        return {"authenticated": True, "message_sent": False}
    except Exception:
        raise RuntimeError("Gmail SMTP authentication failed; details redacted") from None


if __name__ == "__main__":
    result = check()
    print("SMTP_AUTH: authenticated=" + str(int(result["authenticated"]))
          + "; message_sent=0; sender_details=0")
