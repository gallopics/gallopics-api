import re
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class TDBClient:
    SEARCH_PATH = "/meeting/searches"

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    def _parse_html_events(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        events = []

        for row in soup.select("tbody tr"):
            meeting_link = row.find("a", href=re.compile(r"^/meetings/\d+"))
            if not meeting_link:
                continue

            cells = row.find_all("td", recursive=False)
            if len(cells) < 5:
                continue

            href = meeting_link.get("href", "")
            match = re.search(r"/meetings/(\d+)", href)
            if not match:
                continue

            details_cell = cells[4]
            title = details_cell.find("em")
            description = details_cell.find("div")
            start_input = cells[1].find("input", attrs={"name": "start_on"})
            status_cell = cells[-1]
            status_link = status_cell.find("a", href=re.compile(r"^/meetings/\d+"))
            proposition_link = row.find("a", href=re.compile(r"^/meeting_propositions/\d+"))

            event = {
                "id": match.group(1),
                "organizer": meeting_link.get_text(" ", strip=True) or None,
                "name": title.get_text(" ", strip=True) if title else None,
                "description": description.get_text(" ", strip=True) if description else None,
                "start_date": start_input.get("value") if start_input else None,
                "status": (
                    status_link.get_text(" ", strip=True)
                    if status_link
                    else status_cell.get_text(" ", strip=True)
                ),
                "tdb_url": urljoin(str(self._client.base_url), href),
                "proposition_url": (
                    urljoin(str(self._client.base_url), proposition_link.get("href"))
                    if proposition_link
                    else None
                ),
                "is_sustainable": bool(row.find("img", alt=re.compile("MiljöChecken", re.I))),
            }

            if description:
                description_text = description.get_text(" ", strip=True)
                desc_match = re.search(
                    r"tävling i\s+(?P<discipline>.+?)(?:\s+(?P<horse_type>ponny och ridhäst|ponny|ridhäst))?$",
                    description_text,
                    flags=re.I,
                )
                if desc_match:
                    event["discipline"] = desc_match.group("discipline")
                    event["horse_type"] = desc_match.group("horse_type")

            events.append(event)

        return events

    def _last_page_number(self, html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        page_numbers = [1]

        for link in soup.select(".pagination a[href]"):
            href = link.get("href", "")
            query = parse_qs(urlsplit(href).query)
            for value in query.get("page", []):
                if value.isdigit():
                    page_numbers.append(int(value))

        return max(page_numbers)

    def _response_events(self, response: httpx.Response) -> list[dict]:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            data = response.json()
            return data if isinstance(data, list) else data.get("items", [])
        return self._parse_html_events(response.text)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def search_events(
        self,
        params: Optional[dict] = None,
        max_pages: Optional[int] = None,
    ) -> list[dict]:
        events: list[dict] = []
        base_params = params or {}

        response = await self._client.get(self.SEARCH_PATH, params=base_params)
        response.raise_for_status()
        events.extend(self._response_events(response))

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return events

        last_page = self._last_page_number(response.text)
        if max_pages is not None:
            last_page = min(last_page, max_pages)

        for page in range(2, last_page + 1):
            page_params = {**base_params, "page": page}
            response = await self._client.get(self.SEARCH_PATH, params=page_params)
            response.raise_for_status()
            events.extend(self._response_events(response))

        return events

    async def close(self):
        await self._client.aclose()
