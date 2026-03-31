import resend
import structlog

logger = structlog.get_logger()


class ResendClient:
    def __init__(self, api_key: str, from_email: str) -> None:
        resend.api_key = api_key
        self._from_email = from_email

    def send(self, *, to: str, subject: str, body: str) -> str | None:
        params: resend.Emails.SendParams = {
            "from": self._from_email,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        try:
            response = resend.Emails.send(params)
            email_id = response["id"]
            logger.info("email_sent", to=to, subject=subject, email_id=email_id)
            return email_id
        except Exception:
            logger.error("email_send_failed", to=to, subject=subject, exc_info=True)
            return None
