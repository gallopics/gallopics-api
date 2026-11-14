from unittest.mock import AsyncMock, MagicMock

from scripts import sync_equipe


async def test_sync_commits_and_cleans_up(monkeypatch):
    client = MagicMock(close=AsyncMock())
    db = MagicMock(commit=AsyncMock())
    session = MagicMock(__aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=False))
    engine = MagicMock(dispose=AsyncMock())
    sync_from_equipe = AsyncMock(return_value={"created": 2, "updated": 5})

    monkeypatch.setattr(sync_equipe, "EquipeClient", lambda _url: client)
    monkeypatch.setattr(sync_equipe, "async_session_factory", lambda: session)
    monkeypatch.setattr(sync_equipe, "engine", engine)
    monkeypatch.setattr(sync_equipe.EventService, "sync_from_equipe", sync_from_equipe)

    assert await sync_equipe.sync() == {"created": 2, "updated": 5}
    assert sync_from_equipe.await_args.kwargs == {"country": "swe"}
    db.commit.assert_awaited_once()
    client.close.assert_awaited_once()
    engine.dispose.assert_awaited_once()


async def test_sync_cleans_up_when_equipe_fails(monkeypatch):
    client = MagicMock(close=AsyncMock())
    db = MagicMock(commit=AsyncMock())
    session = MagicMock(__aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=False))
    engine = MagicMock(dispose=AsyncMock())

    monkeypatch.setattr(sync_equipe, "EquipeClient", lambda _url: client)
    monkeypatch.setattr(sync_equipe, "async_session_factory", lambda: session)
    monkeypatch.setattr(sync_equipe, "engine", engine)
    monkeypatch.setattr(sync_equipe.EventService, "sync_from_equipe", AsyncMock(side_effect=RuntimeError("Equipe down")))

    try:
        await sync_equipe.sync()
    except RuntimeError:
        pass
    else:
        raise AssertionError("the error must reach systemd")
    db.commit.assert_not_awaited()
    client.close.assert_awaited_once()
    engine.dispose.assert_awaited_once()
