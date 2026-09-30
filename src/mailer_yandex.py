from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def send_yandex_email(
    to: str,
    subject: str,
    body: str,
    *,
    cc: str | None = None,
) -> None:
    user = os.getenv("YANDEX_SMTP_USER", "cco@imon.agency").strip()
    password = os.getenv("YANDEX_SMTP_APP_PASSWORD", "").strip()
    host = os.getenv("YANDEX_SMTP_HOST", "smtp.yandex.com").strip()
    port = int(os.getenv("YANDEX_SMTP_PORT", "465"))

    if not password:
        raise RuntimeError(
            "YANDEX_SMTP_APP_PASSWORD is not set. "
            "Create a Yandex Mail app password and store it locally."
        )

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.set_content(body)

    recipients = [x.strip() for x in to.split(",") if x.strip()]
    if cc:
        recipients.extend(x.strip() for x in cc.split(",") if x.strip())

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg, from_addr=user, to_addrs=recipients)
