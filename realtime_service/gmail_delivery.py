"""Single-recipient Gmail delivery over SMTP/TLS.

The personal Google account is configured by its *app password*, never its
regular password. This module owns no scheduler or automatic sending.
"""
from __future__ import annotations

import re
import smtplib
import ssl
import socket
from email.message import EmailMessage
from email.utils import make_msgid

GMAIL_ADDRESS="famesel7@gmail.com"
GMAIL_SMTP_HOST="smtp.gmail.com"
GMAIL_SMTP_PORT=465
EMAIL_RE=re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def normalize_app_password(value: str) -> str:
    """Google app passwords have 16 alphanumeric characters, often grouped."""
    clean=re.sub(r"\s+","",str(value or "")).lower()
    if not re.fullmatch(r"[a-z0-9]{16}",clean):
        raise ValueError("Нужен пароль приложения Google из 16 символов, не пароль Gmail")
    return clean


def validated_message(to: str, subject: str, body: str) -> EmailMessage:
    to=to.strip()
    subject=subject.strip()
    body=body.strip()
    if not EMAIL_RE.fullmatch(to) or len(to)>254:
        raise ValueError("Недопустимый email получателя")
    if not subject or len(subject)>180 or "\r" in subject or "\n" in subject:
        raise ValueError("Тема письма должна быть не длиннее 180 символов")
    if len(body)<30 or len(body)>6000:
        raise ValueError("Письмо должно содержать от 30 до 6000 символов")
    message=EmailMessage()
    message["From"]=GMAIL_ADDRESS
    message["To"]=to
    message["Subject"]=subject
    message["Message-ID"]=make_msgid(domain="gmail.com")
    message.set_content(body)
    return message


def deliver(message: EmailMessage, app_password: str) -> str:
    """Return RFC Message-ID only after SMTP server accepts DATA."""
    password=normalize_app_password(app_password)
    context=ssl.create_default_context()
    with smtplib.SMTP_SSL(GMAIL_SMTP_HOST,GMAIL_SMTP_PORT,context=context,timeout=25) as server:
        server.login(GMAIL_ADDRESS,password)
        refused=server.send_message(message,from_addr=GMAIL_ADDRESS,
                                    to_addrs=[str(message["To"])])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    return str(message["Message-ID"])
