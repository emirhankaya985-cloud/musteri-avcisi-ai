"""Gmail SMTP transport limited to a deliberate owner-to-self smoke test.

No production lead mail, bulk sending, recipients from OSM, or unattended jobs.
All credentials are read from runtime environment, never printed or persisted.
"""
from email.message import EmailMessage
from email.utils import formataddr
import os
import re
import smtplib
import ssl

from .core import offer

SERVER = "smtp.gmail.com"
PORT = 465
APPROVAL = "YES_ONE_EMAIL_TO_MYSELF"
MAIL_RE = re.compile(r"[a-z0-9][a-z0-9.+_-]*@gmail\.com\Z", re.ASCII)
DISPLAY_NAME = "Emirhan Kaya | Digital Solutions"


def sender_credentials(env):
    """Load SMTP credentials, without ever revealing them in error messages."""
    address = str(env.get("GMAIL_SENDER_ADDRESS") or "").strip().lower()
    if not MAIL_RE.fullmatch(address):
        raise RuntimeError("Gmail sender account not configured or invalid")
    password = "".join(str(env.get("GMAIL_APP_PASSWORD") or "").split())
    if len(password) != 16 or not password.isascii() or not password.isalnum():
        raise RuntimeError("Gmail application password is missing or invalid")
    return address, password


def prepare_offer_draft(lead):
    """Create text for human review, without choosing a recipient or sending."""
    if not isinstance(lead, dict) or not str(lead.get("name") or "").strip():
        raise ValueError("Business name is required for a draft")
    name = str(lead["name"]).replace("\r", " ").replace("\n", " ").strip()
    if len(name) > 100:
        name = name[:100]
    return {
        "subject": f"{name} için dijital çözüm fikri",
        "body": offer({**lead, "name": name}) +
                "\n\nEmirhan Kaya\nWeb Development & AI Automation",
    }


def make_self_test_message(address):
    if not MAIL_RE.fullmatch(address):
        raise ValueError("Invalid self-test Gmail address")
    message = EmailMessage()
    message["From"] = formataddr((DISPLAY_NAME, address))
    message["To"] = address
    message["Subject"] = "Müşteri Avcısı AI — Gmail bağlantı testi"
    message.set_content(
        "Merhaba,\n\n"
        "Bu ileti Müşteri Avcısı AI tarafından kendi Gmail adresine "
        "gönderilen tek seferlik bağlantı testidir.\n"
        "Gerçek işletmelere mesaj veya e-posta gönderilmedi.\n\n"
        "Emirhan Kaya\n"
    )
    return message


def send_to_self(env=None, smtp_factory=None, output=print):
    """Send exactly one message from/to the same Gmail only by explicit opt-in.

    A future external-recipient mailer must be built separately with verified
    individual approvals, legal compliance, and private idempotency storage.
    """
    env = os.environ if env is None else env
    if env.get("GMAIL_SELF_TEST_APPROVED") != APPROVAL:
        raise RuntimeError("Explicit self-test approval required; no mail sent")
    address, password = sender_credentials(env)
    message = make_self_test_message(address)
    factory = smtplib.SMTP_SSL if smtp_factory is None else smtp_factory
    try:
        with factory(SERVER, PORT, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(address, password)
            refused = smtp.send_message(message, from_addr=address, to_addrs=[address])
            if refused:
                raise RuntimeError("Gmail self-test delivery rejected")
    except (smtplib.SMTPException, OSError, TimeoutError, RuntimeError):
        # Gmail SMTP exceptions may contain both credentials and addresses.
        raise RuntimeError("Gmail SMTP self-test failed; sensitive details redacted") from None
    output("GMAIL_OWNER_SELF_TEST: 1 accepted by SMTP (inbox delivery not independently verified)")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Safe Gmail smoke test only")
    parser.add_argument("mode", choices=("dry-run", "send-to-self"))
    mode = parser.parse_args().mode
    if mode == "dry-run":
        # Safe even when no Gmail account or Secrets have been configured.
        print("GMAIL_DRY_RUN_OK: sender=self only; no network or email sent")
    else:
        send_to_self()


if __name__ == "__main__":
    main()
