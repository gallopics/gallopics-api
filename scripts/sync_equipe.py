"""Sync Swedish Equipe meetings into events.

Run from the API folder (it reads `.env` there), e.g. by the nightly systemd timer:

    .venv/bin/python -m scripts.sync_equipe

A fresh process per run: the Celery task reused one connection pool across
event loops and only worked once per worker start.
"""

import asyncio
import json

from app.config import get_settings
from app.database import async_session_factory, engine
from app.integrations.equipe.client import EquipeClient
from app.services.event_service import EventService


async def sync() -> dict:
    client = EquipeClient(get_settings().equipe_base_url)
    try:
        async with async_session_factory() as db:
            result = await EventService(db).sync_from_equipe(client, country="swe")
            await db.commit()
            return result
    finally:
        await client.close()
        await engine.dispose()


def main() -> None:
    # Any error exits non-zero, so systemd marks the run as failed
    print(json.dumps(asyncio.run(sync()), default=str))


if __name__ == "__main__":
    main()
