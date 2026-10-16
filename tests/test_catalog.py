from __future__ import annotations

import aiohttp
import pytest

from conftest import wait_until

from station.catalog import SpoolCatalog, SpoolMeta, meta_from_api
from station.sim.spoolman import SimSpoolman
from station.spoolman import SpoolmanClient


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def rig():  # noqa: ANN201
    sim = SimSpoolman()
    url = await sim.start()
    session = aiohttp.ClientSession()
    client = SpoolmanClient(url, session, writes=True)
    updates: list[int] = []
    clock = Clock()
    catalog = SpoolCatalog(client, lambda: updates.append(1), ttl_s=60, retry_s=10, clock=clock)
    yield sim, catalog, updates, clock
    await catalog.stop()
    await session.close()
    await sim.stop()


def gets(sim: SimSpoolman, spool_id: int) -> int:
    return sum(1 for method, path, _ in sim.requests if method == "GET" and path == f"/api/v1/spool/{spool_id}")


async def test_fetches_in_background_then_caches(rig) -> None:  # noqa: ANN001
    sim, catalog, updates, clock = rig
    assert catalog.get(93) is None
    await wait_until(lambda: updates)
    assert catalog.get(93) == SpoolMeta(initial_g=1000.0, colors=("#C94CE0", "#33B5E5", "#F2C14E"))
    assert gets(sim, 93) == 1
    clock.now += 61
    assert catalog.get(93) is not None
    await wait_until(lambda: gets(sim, 93) == 2)
    assert len(updates) == 1


async def test_missing_spools_are_cached_and_errors_retry_later(rig) -> None:  # noqa: ANN001
    sim, catalog, updates, clock = rig
    catalog.get(999)
    await wait_until(lambda: updates)
    assert catalog.get(999) is None and gets(sim, 999) == 1
    sim.online = False
    catalog.get(84)
    await wait_until(lambda: gets(sim, 84) == 1)
    await wait_until(lambda: not catalog._tasks)  # noqa: SLF001
    catalog.get(84)
    assert gets(sim, 84) == 1
    sim.online = True
    clock.now += 11
    catalog.get(84)
    await wait_until(lambda: catalog.get(84) is not None)


async def test_put_updates_without_fetching(rig) -> None:  # noqa: ANN001
    sim, catalog, updates, _ = rig
    data = sim.get(97)
    catalog.put(data)
    catalog.put(data)
    assert updates == [1]
    assert catalog.get(97) == meta_from_api(data)
    assert gets(sim, 97) == 0


def test_meta_falls_back_to_filament_weight() -> None:
    assert meta_from_api({"filament": {"weight": 750, "color_hex": "00ff00"}}) == SpoolMeta(750.0, ("#00FF00",))
    assert meta_from_api({"initial_weight": 0, "filament": {}}) == SpoolMeta(None, ())


def test_get_without_event_loop_returns_cached_only() -> None:
    catalog = SpoolCatalog(SpoolmanClient("http://127.0.0.1:9/api/v1", None, writes=False),  # type: ignore[arg-type]
                           lambda: None)
    assert catalog.get(1) is None
