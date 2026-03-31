from __future__ import annotations

import time

import httpx
import structlog

logger = structlog.get_logger(__name__)


class TwentyClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._graphql_url = f"{base_url.rstrip('/')}/graphql"
        self._http = httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _query(self, query: str, variables: dict | None = None) -> dict:
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self._http.post(self._graphql_url, json=payload)
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")

        return data

    def fetch_all(self, collection: str, fields: str, *, max_pages: int = 50) -> list[dict]:
        nodes: list[dict] = []
        cursor: str | None = None

        for page_num in range(max_pages):
            if page_num > 0:
                time.sleep(0.6)

            after_clause = f', after: "{cursor}"' if cursor else ""
            query = (
                f"{{ {collection}(first: 200{after_clause}) {{"
                f"  edges {{ cursor node {{ {fields} }} }}"
                f"  pageInfo {{ hasNextPage endCursor }}"
                f"}} }}"
            )

            result = self._query(query)
            collection_data = result["data"][collection]
            edges = collection_data["edges"]
            page_info = collection_data["pageInfo"]

            for edge in edges:
                nodes.append(edge["node"])

            if not page_info["hasNextPage"]:
                break

            cursor = page_info["endCursor"]
        else:
            raise RuntimeError(
                f"fetch_all exceeded max_pages={max_pages} for collection '{collection}'"
            )

        logger.info("fetch_all complete", collection=collection, total=len(nodes))
        return nodes

    def close(self) -> None:
        self._http.close()
