import httpx
import pytest
import respx

from app.integrations.tdb.client import TDBClient


@pytest.fixture
def tdb_base_url():
    return "https://tdb.example.com"


@pytest.fixture
def tdb_client(tdb_base_url):
    return TDBClient(tdb_base_url)


@respx.mock
async def test_search_events_success(tdb_client, tdb_base_url):
    mock_data = [{"id": "1", "name": "Event A"}, {"id": "2", "name": "Event B"}]
    respx.get(f"{tdb_base_url}/meeting/searches").mock(
        return_value=httpx.Response(200, json=mock_data)
    )
    result = await tdb_client.search_events()
    assert len(result) == 2
    assert result[0]["name"] == "Event A"


@respx.mock
async def test_search_events_with_params(tdb_client, tdb_base_url):
    respx.get(f"{tdb_base_url}/meeting/searches").mock(
        return_value=httpx.Response(200, json=[])
    )
    result = await tdb_client.search_events(params={"discipline": "dressage"})
    assert result == []
    assert respx.calls[0].request.url.params["discipline"] == "dressage"


@respx.mock
async def test_search_events_retry_on_500(tdb_client, tdb_base_url):
    route = respx.get(f"{tdb_base_url}/meeting/searches")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json=[{"id": "1"}]),
    ]
    result = await tdb_client.search_events()
    assert len(result) == 1
    assert route.call_count == 3


@respx.mock
async def test_search_events_parses_tdb_html(tdb_client, tdb_base_url):
    html = """
    <html><body>
      <table><tbody>
        <tr>
          <td class="span1 text-nowrap">v14</td>
          <td>
            <input type="hidden" name="start_on" value="2026-04-04" />
            2026-04-04&nbsp;(1)
          </td>
          <td><a href="/clubs/447"><img alt="" /></a></td>
          <td><img alt="MiljöChecken" /></td>
          <td>
            <a href="/meetings/81733">Olofströms Ridklubb</a>
            <em>Påskhoppet</em>
            <div>2* och 1* tävling i Hoppning ridhäst</div>
          </td>
          <td><a href="/meeting_propositions/38260">Proposition</a></td>
          <td><span class="label success"><a href="/meetings/81733">Resultat</a></span></td>
        </tr>
      </tbody></table>
    </body></html>
    """
    respx.get(f"{tdb_base_url}/meeting/searches").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )

    result = await tdb_client.search_events()

    assert result == [
        {
            "id": "81733",
            "organizer": "Olofströms Ridklubb",
            "name": "Påskhoppet",
            "description": "2* och 1* tävling i Hoppning ridhäst",
            "start_date": "2026-04-04",
            "status": "Resultat",
            "tdb_url": f"{tdb_base_url}/meetings/81733",
            "proposition_url": f"{tdb_base_url}/meeting_propositions/38260",
            "is_sustainable": True,
            "discipline": "Hoppning",
            "horse_type": "ridhäst",
        }
    ]


@respx.mock
async def test_search_events_fetches_all_pages_from_pagination(tdb_client, tdb_base_url):
    page_1 = """
    <table><tbody>
      <tr>
        <td>v14</td><td><input name="start_on" value="2026-04-04" /></td><td></td><td></td>
        <td><a href="/meetings/1">Club A</a><em>Event A</em><div>1* tävling i Hoppning ponny</div></td>
        <td></td><td><a href="/meetings/1">Öppen</a></td>
      </tr>
    </tbody></table>
    <div class="pagination">
      <a href="/meeting/searches?page=1">1</a>
      <a href="/meeting/searches?page=2">2</a>
      <a href="/meeting/searches?page=3">3</a>
      <a rel="next" href="/meeting/searches?page=2">Nästa</a>
    </div>
    """
    page_2 = """
    <table><tbody>
      <tr>
        <td>v15</td><td><input name="start_on" value="2026-04-05" /></td><td></td><td></td>
        <td><a href="/meetings/2">Club B</a><em>Event B</em><div>2* tävling i Dressyr ridhäst</div></td>
        <td></td><td><a href="/meetings/2">Stängd</a></td>
      </tr>
    </tbody></table>
    """
    page_3 = """
    <table><tbody>
      <tr>
        <td>v16</td><td><input name="start_on" value="2026-04-06" /></td><td></td><td></td>
        <td><a href="/meetings/3">Club C</a><em>Event C</em><div>1* tävling i Hoppning ridhäst</div></td>
        <td></td><td><a href="/meetings/3">Resultat</a></td>
      </tr>
    </tbody></table>
    """
    route = respx.get(f"{tdb_base_url}/meeting/searches")
    route.side_effect = [
        httpx.Response(200, text=page_1, headers={"content-type": "text/html"}),
        httpx.Response(200, text=page_2, headers={"content-type": "text/html"}),
        httpx.Response(200, text=page_3, headers={"content-type": "text/html"}),
    ]

    result = await tdb_client.search_events()

    assert [event["id"] for event in result] == ["1", "2", "3"]
    assert [call.request.url.params.get("page") for call in respx.calls] == [None, "2", "3"]


@respx.mock
async def test_search_events_preserves_params_when_fetching_pages(tdb_client, tdb_base_url):
    page_1 = """
    <table><tbody>
      <tr>
        <td>v14</td><td><input name="start_on" value="2026-04-04" /></td><td></td><td></td>
        <td><a href="/meetings/1">Club A</a><em>Event A</em><div>1* tävling i Hoppning ponny</div></td>
        <td></td><td><a href="/meetings/1">Öppen</a></td>
      </tr>
    </tbody></table>
    <div class="pagination">
      <a href="/meeting/searches?page=1">1</a>
      <a href="/meeting/searches?page=2">2</a>
    </div>
    """
    page_2 = """
    <table><tbody>
      <tr>
        <td>v15</td><td><input name="start_on" value="2026-04-05" /></td><td></td><td></td>
        <td><a href="/meetings/2">Club B</a><em>Event B</em><div>2* tävling i Dressyr ridhäst</div></td>
        <td></td><td><a href="/meetings/2">Stängd</a></td>
      </tr>
    </tbody></table>
    """
    route = respx.get(f"{tdb_base_url}/meeting/searches")
    route.side_effect = [
        httpx.Response(200, text=page_1, headers={"content-type": "text/html"}),
        httpx.Response(200, text=page_2, headers={"content-type": "text/html"}),
    ]

    result = await tdb_client.search_events(params={"search[discipline_id]": "2"})

    assert [event["id"] for event in result] == ["1", "2"]
    assert [call.request.url.params.get("search[discipline_id]") for call in respx.calls] == ["2", "2"]
    assert [call.request.url.params.get("page") for call in respx.calls] == [None, "2"]
