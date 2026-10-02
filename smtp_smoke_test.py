import os
import smtplib
from email.message import EmailMessage

def sanitize(message: str) -> str:
    text = str(message or "")
    for key in ("SMTP_PASSWORD", "SMTP_USERNAME", "SMTP_FROM_EMAIL", "GMAIL_LEAD_RECIPIENT"):
        value = os.getenv(key) or ""
        if value:
            text = text.replace(value, "***")
    return text[:160]

host = os.environ["SMTP_HOST"]
port = int(os.getenv("SMTP_PORT", "465"))
username = os.environ["SMTP_USERNAME"]
password = os.environ["SMTP_PASSWORD"]
sender = os.environ["SMTP_FROM_EMAIL"]
recipient = os.environ["GMAIL_LEAD_RECIPIENT"]

try:
    smtp = smtplib.SMTP_SSL(host, port, timeout=30)
    smtp.login(username, password)
    print("SMTP_AUTH_OK", flush=True)
except Exception as exc:
    print(f"SMTP_AUTH_FAIL {type(exc).__name__}: {sanitize(exc)}", flush=True)
    raise

msg = EmailMessage()
msg["From"] = sender
msg["To"] = recipient
msg["Subject"] = "Ashlar HAL SMTP test"
msg.set_content("SiteGround SMTP validation successful.")

try:
    smtp.send_message(msg)
    smtp.quit()
    print("SMTP_SEND_OK", flush=True)
except Exception as exc:
    print(f"SMTP_SEND_FAIL {type(exc).__name__}: {sanitize(exc)}", flush=True)
    raise
