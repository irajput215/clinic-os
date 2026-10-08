import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import emails
from jinja2 import Template

from app.core.config import settings
from app.core.password_bound_tokens import LinkClaims, PasswordBoundToken

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EmailData:
    html_content: str
    subject: str


def render_email_template(*, template_name: str, context: dict[str, Any]) -> str:
    template_str = (
        Path(__file__).parent / "email-templates" / template_name
    ).read_text()
    template: Template = Template(template_str)
    html_content = template.render(context)
    return html_content


def _smtp_options() -> dict[str, Any]:
    smtp_options: dict[str, Any] = {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
    }
    if settings.SMTP_TLS:
        smtp_options["tls"] = True
    elif settings.SMTP_SSL:
        smtp_options["ssl"] = True
    if settings.SMTP_USER:
        smtp_options["user"] = settings.SMTP_USER
    if settings.SMTP_PASSWORD:
        smtp_options["password"] = settings.SMTP_PASSWORD
    return smtp_options


def _message(*, subject: str, html_content: str) -> emails.message.Message:
    assert settings.EMAILS_FROM_EMAIL  # For type checker
    return emails.message.Message(
        subject=subject,
        html=html_content,
        mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
    )


def send_email(
    *,
    email_to: str,
    subject: str = "",
    html_content: str = "",
) -> None:
    assert settings.emails_enabled, "no provided configuration for email variables"
    message = _message(subject=subject, html_content=html_content)
    response = message.send(to=email_to, smtp=_smtp_options())
    logger.info(f"send email result: {response}")


def deliver_email(*, email_to: str, subject: str, html_content: str) -> bool:
    """Send one email and say whether the server accepted it. Logs nothing.

    For mail that goes to a patient (`app.modules.appointments.notifications`): the caller records
    the outcome as a code, so neither the address nor the server's reply text (which can quote the
    address back) ever reaches a log line. A connection failure is `False`, never an exception.
    """
    assert settings.emails_enabled, "no provided configuration for email variables"
    message = _message(subject=subject, html_content=html_content)
    try:
        response = message.send(to=email_to, smtp=_smtp_options())
    except Exception:  # noqa: BLE001 - any failure to hand over is "not accepted"
        return False
    return bool(response.success)


def generate_test_email(email_to: str) -> EmailData:
    project_name = settings.PROJECT_NAME
    subject = f"{project_name} - Test email"
    html_content = render_email_template(
        template_name="test_email.html",
        context={"project_name": settings.PROJECT_NAME, "email": email_to},
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_reset_password_email(email_to: str, email: str, token: str) -> EmailData:
    project_name = settings.PROJECT_NAME
    subject = f"{project_name} - Password recovery for user {email}"
    link = f"{settings.FRONTEND_HOST}/reset-password?token={token}"
    html_content = render_email_template(
        template_name="reset_password.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "username": email,
            "email": email_to,
            "valid_hours": settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS,
            "link": link,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_new_account_email(
    email_to: str, username: str, password: str
) -> EmailData:
    project_name = settings.PROJECT_NAME
    subject = f"{project_name} - New account for user {username}"
    html_content = render_email_template(
        template_name="new_account.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "username": username,
            "password": password,
            "email": email_to,
            "link": settings.FRONTEND_HOST,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


# Recovery links share the invitation links' mechanism (`app.core.password_bound_tokens`): signed
# with their own derived key, expiring, and bound to the password hash at issue, so a link sets a
# password once and any later password change retires it.
_RESET_LINK = PasswordBoundToken(
    purpose="password-reset", key_label=b"clinicos/password-reset/v1"
)


def generate_password_reset_token(
    *, email: str, hashed_password: str, now: datetime | None = None
) -> str:
    return _RESET_LINK.issue(
        subject=email,
        hashed_password=hashed_password,
        lifetime=timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS),
        now=now,
    )


def verify_password_reset_token(token: str) -> LinkClaims | None:
    """The claims of a valid, unexpired recovery link. Whether it is spent is the caller's check."""
    return _RESET_LINK.read(token)


def password_reset_token_unspent(claims: LinkClaims, hashed_password: str) -> bool:
    return _RESET_LINK.still_unspent(claims, hashed_password)
