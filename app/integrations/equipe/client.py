from typing import Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class EquipeClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def get_meetings(self, params: Optional[dict] = None) -> list[dict]:
        response = await self._client.get("/meetings", params=params or {})
        response.raise_for_status()
        return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def get_meeting_results(self, meeting_id: str) -> list[dict]:
        response = await self._client.get(f"/meetings/{meeting_id}/results")
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self._client.aclose()
