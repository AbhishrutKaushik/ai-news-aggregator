"""Email service — sends the HTML digest via Gmail SMTP.

Uses TLS (port 587) with a Gmail App Password.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Sends HTML emails via SMTP (configured for Gmail by default)."""

    def send(
        self,
        subject: str,
        html_body: str,
        recipients: list[str] | None = None,
        *,
        show_in_header: bool = False,
    ) -> bool:
        """Send an HTML email using the credentials in settings.

        Args:
            subject: Email subject line.
            html_body: Rendered HTML content.
            recipients: Optional explicit list of recipients.
                        Falls back to settings.email_to_list if not provided.
            show_in_header: If True, recipients will appear in the "To" header.
                            By default the recipients are treated as BCC (they
                            are still passed to SMTP but not shown in the
                            message headers).

        Returns True on success, False on failure.
        """
        if recipients is None:
            recipients = settings.email_to_list

        if not settings.email_from or not recipients or not settings.email_password:
            logger.error("Email credentials not configured in .env — skipping send.")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.email_from

        # The recipients list is always passed to ``sendmail`` but by default we
        # don't put them in the `To` header so that they behave like BCC.  If the
        # caller explicitly passes ``show_in_header=True`` we populate the header
        # for debugging.
        if show_in_header:
            msg["To"] = ", ".join(recipients)
        else:
            # use a generic placeholder (self-address) so some clients don't drop
            # the message entirely
            msg["To"] = settings.email_from

        # Attach HTML body (with a plain-text fallback)
        plain_text = f"View this email in an HTML-capable client.\n\n{subject}"
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=30) as server:
                server.starttls()
                server.login(settings.email_from, settings.email_password)
                server.sendmail(settings.email_from, recipients, msg.as_string())

            logger.info("Digest email sent to %s", ", ".join(recipients))
            return True

        except TimeoutError:
            logger.error(
                "SMTP connection timed out. Port %d may be blocked by your network. "
                "Try a different network or use an HTTP-based email service.",
                settings.email_smtp_port,
            )
            return False

        except smtplib.SMTPAuthenticationError:
            logger.error(
                "SMTP authentication failed. Check EMAIL_FROM and EMAIL_PASSWORD in .env. "
                "For Gmail, use a 16-char App Password (not your regular password)."
            )
            return False

        except Exception as e:
            logger.exception("Failed to send email: %s", e)
            return False
