from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from pipeline_coach.ingestion.twenty_client import TwentyClient


def _make_page(nodes: list[dict], has_next: bool, end_cursor: str | None) -> dict:
    """Build a fake GraphQL response for a single paginated page."""
    return {
        "data": {
            "people": {
                "edges": [{"cursor": f"cur-{i}", "node": n} for i, n in enumerate(nodes)],
                "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
            }
        }
    }


@pytest.fixture()
def client() -> TwentyClient:
    return TwentyClient(base_url="https://crm.example.com", api_key="test-key")


def _mock_response(json_data: dict, raise_status: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_data
    if raise_status:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=MagicMock()
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Single-page fetch
# ---------------------------------------------------------------------------


def test_fetch_all_single_page(client: TwentyClient, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _make_page([{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}], False, None)
    mock_post = MagicMock(return_value=_mock_response(page))
    monkeypatch.setattr(client, "_http", MagicMock(post=mock_post))

    result = client.fetch_all("people", "id name")

    assert result == [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]
    assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# Multi-page fetch
# ---------------------------------------------------------------------------


def test_fetch_all_multi_page(client: TwentyClient, monkeypatch: pytest.MonkeyPatch) -> None:
    page1 = _make_page([{"id": "1"}], True, "cursor-abc")
    page2 = _make_page([{"id": "2"}], False, None)

    responses = [_mock_response(page1), _mock_response(page2)]
    mock_post = MagicMock(side_effect=responses)
    monkeypatch.setattr(client, "_http", MagicMock(post=mock_post))

    result = client.fetch_all("people", "id")

    assert result == [{"id": "1"}, {"id": "2"}]
    assert mock_post.call_count == 2

    # Second call must pass the cursor from page 1
    second_call_body = mock_post.call_args_list[1].kwargs.get(
        "json",
        mock_post.call_args_list[1].args[1] if len(mock_post.call_args_list[1].args) > 1 else {},
    )
    assert "cursor-abc" in str(second_call_body)


# ---------------------------------------------------------------------------
# GraphQL error raises RuntimeError
# ---------------------------------------------------------------------------


def test_query_raises_on_graphql_errors(
    client: TwentyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    error_resp = {"errors": [{"message": "Field 'badField' not found"}]}
    mock_post = MagicMock(return_value=_mock_response(error_resp))
    monkeypatch.setattr(client, "_http", MagicMock(post=mock_post))

    with pytest.raises(RuntimeError, match="GraphQL errors"):
        client._query("{ people { edges { node { badField } } } }")


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_fetch_all_circuit_breaker(client: TwentyClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """max_pages=1 with hasNextPage=True should raise after the first page."""
    page = _make_page([{"id": "1"}], True, "cursor-infinite")
    mock_post = MagicMock(return_value=_mock_response(page))
    monkeypatch.setattr(client, "_http", MagicMock(post=mock_post))

    with pytest.raises(RuntimeError, match="max_pages"):
        client.fetch_all("people", "id", max_pages=1)


# ---------------------------------------------------------------------------
# HTTP error propagates
# ---------------------------------------------------------------------------


def test_fetch_all_http_error_propagates(
    client: TwentyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_post = MagicMock(return_value=_mock_response({}, raise_status=True))
    monkeypatch.setattr(client, "_http", MagicMock(post=mock_post))

    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_all("people", "id")
