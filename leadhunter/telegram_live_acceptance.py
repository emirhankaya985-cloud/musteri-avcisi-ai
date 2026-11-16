"""One owner-only Telegram API acceptance check, no customer/outreach messages.

Test key is committed in private Neon before network access. Re-running the
workflow can never send a duplicate. Telegram API ok != phone delivery.
"""
import json
import os
import re
from urllib.request import Request, urlopen

from .review_private import connect_private_database

TEST_KEY="owner_alert_acceptance_20261116"


def send_once(env=None,db=None,opener=urlopen,output=print):
    env=os.environ if env is None else env
    token=str(env.get("TELEGRAM_BOT_TOKEN","")).strip()
    chat=str(env.get("TELEGRAM_CHAT_ID","")).strip()
    if not re.fullmatch(r"[0-9]{7,12}:[A-Za-z0-9_-]{30,}",token):
        raise RuntimeError("Owner Telegram bot token missing/invalid; no call made")
    if not re.fullmatch(r"-?[0-9]{3,19}",chat):
        raise RuntimeError("Owner Telegram chat ID missing/invalid; no call made")
    if env.get("AUTO_MAIL_ENABLED") != "false":
        raise RuntimeError("SMTP safety lock must be explicitly disabled")
    own=db is None
    conn=connect_private_database(env.get("REVIEW_DATABASE_URL")) if own else db
    claimed=False
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO owner_telegram_alert_acceptance(test_key,state) "
                    "VALUES (%s,'reserved') ON CONFLICT DO NOTHING RETURNING test_key",
                    (TEST_KEY,))
                claimed=cur.fetchone() is not None
        if not claimed:
            output("TELEGRAM_ACCEPTANCE: already_claimed=1; duplicate_sent=0")
            return False
        url="https://api.telegram.org/bot"+token+"/"
        accepted=False
        api_msgid=None
        try:
            with opener(Request(url+"getMe",headers={"Accept":"application/json"}),
                        timeout=12) as response:
                identity=json.loads(response.read(65536))
            if identity.get("ok") is not True or not isinstance(identity.get("result"),dict):
                raise RuntimeError("Telegram owner bot authorization failed")
            message={
                "chat_id":chat,
                "text":("Müşteri Avcısı AI · Tek seferlik kritik bildirim kabul testi. "
                        "402/402 ilk tarama korunuyor. "
                        "Yeni müşteri e-postası gönderilmedi."),
                "disable_notification":False
            }
            payload=json.dumps(message,ensure_ascii=False).encode("utf-8")
            req=Request(url+"sendMessage",data=payload,
                        headers={"Content-Type":"application/json",
                                 "Accept":"application/json"},method="POST")
            with opener(req,timeout=12) as response:
                result=json.loads(response.read(65536))
            api_msgid=result.get("result",{}).get("message_id")
            accepted=result.get("ok") is True and type(api_msgid) is int and api_msgid>0
        except Exception:
            # An exception can contain the secret URL or original chat data.
            # Do NOT print it. At-most-once claim remains permanently reserved.
            accepted=False
            api_msgid=None
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE owner_telegram_alert_acceptance "
                    "SET state=%s,api_message_id=%s,verified_at=now() "
                    "WHERE test_key=%s AND state='reserved'",
                    ("api_accepted" if accepted else "failed",api_msgid,TEST_KEY))
        output("TELEGRAM_ACCEPTANCE: owner_bot_api_accepted="+str(int(accepted))+
               "; duplicate_sent=0; customer_mail_sent=0")
        if not accepted:
            raise RuntimeError("Owner Telegram API acceptance not confirmed")
        return True
    finally:
        if own:
            conn.close()


if __name__=="__main__":
    send_once()
