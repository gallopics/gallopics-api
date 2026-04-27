import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class KlarnaClient:
    def __init__(self, api_url: str, username: str, password: str):
        self._client = httpx.AsyncClient(
            base_url=api_url,
            auth=(username, password),
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def create_session(self, payload: dict) -> dict:
        resp = await self._client.post("/payments/v1/sessions", json=payload)
        resp.raise_for_status()
        return resp.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def create_order(self, authorization_token: str, payload: dict) -> dict:
        resp = await self._client.post(
            f"/payments/v1/authorizations/{authorization_token}/order", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def capture(self, order_id: str, payload: dict) -> None:
        resp = await self._client.post(
            f"/ordermanagement/v1/orders/{order_id}/captures", json=payload
        )
        resp.raise_for_status()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def refund(self, order_id: str, payload: dict) -> None:
        resp = await self._client.post(
            f"/ordermanagement/v1/orders/{order_id}/refunds", json=payload
        )
        resp.raise_for_status()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def cancel(self, order_id: str) -> None:
        resp = await self._client.post(
            f"/ordermanagement/v1/orders/{order_id}/cancel"
        )
        resp.raise_for_status()

    async def close(self):
        await self._client.aclose()
