from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from watchdiff.models import DiffReport, EmailConfig


def send_email(config: EmailConfig, report: DiffReport) -> None:
    smtp = config.smtp
    use_ssl = smtp.secure if smtp.secure is not None else smtp.port == 465

    from_addr = config.from_ or f"{smtp.user}@{smtp.host}"
    to_addrs  = [config.to] if isinstance(config.to, str) else list(config.to)
    subject   = config.subject or f"[WatchDiff] Change detected: {report.label}"

    body_lines = [report.summary(), ""]
    for change in report.changes:
        body_lines.append(change.human())
    body = "\n".join(body_lines)

    msg = MIMEMultipart()
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if use_ssl:
        with smtplib.SMTP_SSL(smtp.host, smtp.port) as server:
            server.login(smtp.user, smtp.password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
    else:
        with smtplib.SMTP(smtp.host, smtp.port) as server:
            server.starttls()
            server.login(smtp.user, smtp.password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
