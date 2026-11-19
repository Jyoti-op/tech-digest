"""Delivery: send via SMTP, or write files in dry-run mode."""
from __future__ import annotations

import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path


def write_preview(out_dir: str, email: str, html_body: str) -> Path:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = Path(out_dir) / f"digest_{re.sub(r'[^a-zA-Z0-9]+', '_', email)}.html"
    path.write_text(html_body, encoding="utf-8")
    return path


def send_smtp(smtp_cfg: dict, to: str, subject: str, html_body: str, text_body: str) -> None:
    password = os.environ.get(smtp_cfg.get("password_env", "DIGEST_SMTP_PASSWORD"), "")
    if not smtp_cfg.get("username") or not password:
        raise RuntimeError("SMTP username/password not configured (see README)")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, smtp_cfg["from"], to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(smtp_cfg["host"], smtp_cfg["port"], timeout=30) as s:
        s.starttls()
        s.login(smtp_cfg["username"], password)
        s.send_message(msg)
