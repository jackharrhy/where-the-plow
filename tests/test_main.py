# tests/test_main.py
import os
import tempfile
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    with patch.dict(os.environ, {"DB_PATH": path}):
        # Patch collector.run so it doesn't actually poll
        with patch("where_the_plow.collector.run", new_callable=AsyncMock) as mock_run:
            # Make the mock hang forever (simulating a long-running background task)
            async def hang_forever(db, store):
                import asyncio

                await asyncio.Event().wait()

            mock_run.side_effect = hang_forever

            # Need to reload modules to pick up env changes
            import importlib
            import where_the_plow.config

            importlib.reload(where_the_plow.config)
            import where_the_plow.main

            importlib.reload(where_the_plow.main)

            with TestClient(where_the_plow.main.app) as client:
                yield client

    if os.path.exists(path):
        os.unlink(path)


def test_health(test_client):
    db = test_client.app.state.db

    with patch.object(db, "ping", wraps=db.ping) as ping:
        resp = test_client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert ping.call_count == 1
