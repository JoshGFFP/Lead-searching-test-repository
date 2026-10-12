"""Send the report by email over SMTP (works with Purelymail, Gmail, Outlook...)."""

import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import config


class EmailNotConfigured(RuntimeError):
    pass


def send(subject: str, text: str, html: str, attachments: list[str] | None = None):
    missing = [name for name, value in (("SMTP_USERNAME", config.SMTP_USERNAME),
                                        ("SMTP_PASSWORD", config.SMTP_PASSWORD),
                                        ("EMAIL_TO", config.EMAIL_TO)) if not value]
    if missing:
        raise EmailNotConfigured(f"Email settings missing: {', '.join(missing)}")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(config.EMAIL_TO)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=config.EMAIL_FROM.split("@")[-1] or None)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for path in attachments or []:
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(path))

    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context, timeout=60) as s:
            s.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=60) as s:
            s.starttls(context=context)
            s.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            s.send_message(msg)
