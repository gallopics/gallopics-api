import httpx
import pytest
import respx

from app.integrations.equipe.client import EquipeClient


@pytest.fixture
def equipe_base_url():
    return "https://equipe.example.com"


@pytest.fixture
def equipe_client(equipe_base_url):
    return EquipeClient(equipe_base_url)


@respx.mock
async def test_get_meetings_success(equipe_client, equipe_base_url):
    respx.get(f"{equipe_base_url}/meetings/recent").mock(
        return_value=httpx.Response(200, json=[{"id": "m1", "name": "Meeting 1"}])
    )
    result = await equipe_client.get_meetings()
    assert len(result) == 1


@respx.mock
async def test_get_meetings_unwraps_payload(equipe_client, equipe_base_url):
    respx.get(f"{equipe_base_url}/meetings/recent").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "m1", "name": "Meeting 1"}]})
    )
    result = await equipe_client.get_meetings(params={"country": "swe"})
    assert result == [{"id": "m1", "name": "Meeting 1"}]


@respx.mock
async def test_get_meeting_results_success(equipe_client, equipe_base_url):
    respx.get(f"{equipe_base_url}/meetings/m1/results").mock(
        return_value=httpx.Response(200, json=[{"participantName": "Alice"}])
    )
    result = await equipe_client.get_meeting_results("m1")
    assert len(result) == 1


@respx.mock
async def test_retry_on_transient_error(equipe_client, equipe_base_url):
    route = respx.get(f"{equipe_base_url}/meetings/recent")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json=[]),
    ]
    result = await equipe_client.get_meetings()
    assert result == []
    assert route.call_count == 2
