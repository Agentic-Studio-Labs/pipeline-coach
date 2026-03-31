from __future__ import annotations

from unittest.mock import patch

import pytest
from pipeline_coach.delivery.email_client import ResendClient


@pytest.fixture()
def client() -> ResendClient:
    return ResendClient(api_key="test-key", from_email="coach@demo.com")


def test_sets_api_key_on_init() -> None:
    import resend

    ResendClient(api_key="my-key", from_email="x@demo.com")
    assert resend.api_key == "my-key"


def test_send_calls_resend_with_correct_params(client: ResendClient) -> None:
    mock_response = {"id": "email-abc123"}
    with patch("resend.Emails.send", return_value=mock_response) as mock_send:
        result = client.send(
            to="ae@demo.com", subject="Pipeline Issues", body="Here are your issues."
        )

    mock_send.assert_called_once_with(
        {
            "from": "coach@demo.com",
            "to": ["ae@demo.com"],
            "subject": "Pipeline Issues",
            "text": "Here are your issues.",
        }
    )
    assert result == "email-abc123"


def test_send_returns_email_id_on_success(client: ResendClient) -> None:
    with patch("resend.Emails.send", return_value={"id": "xyz-999"}):
        result = client.send(to="ae@demo.com", subject="Subject", body="Body")

    assert result == "xyz-999"


def test_send_returns_none_on_error(client: ResendClient) -> None:
    with patch("resend.Emails.send", side_effect=Exception("API error")):
        result = client.send(to="ae@demo.com", subject="Subject", body="Body")

    assert result is None
