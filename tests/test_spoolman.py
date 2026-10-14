from __future__ import annotations

import aiohttp
import pytest

from station.sim.spoolman import SimSpoolman, load_spool_fixtures
from station.spoolman import (
    SpoolmanClient,
    SpoolmanError,
    SpoolNotFound,
    spool_color,
    spool_info_from_api,
    spool_tare,
)


@pytest.fixture
async def spoolman():  # noqa: ANN201
    sim = SimSpoolman()
    url = await sim.start()
    session = aiohttp.ClientSession()
    health: list[bool] = []
    client = SpoolmanClient(url, session, writes=True, on_health=health.append)
    yield sim, client, health
    await session.close()
    await sim.stop()


async def test_get_spool_and_health(spoolman) -> None:  # noqa: ANN001
    sim, client, health = spoolman
    spool = await client.get_spool(97)
    assert spool["filament"]["vendor"]["name"] == "Sunlu"
    assert await client.health() is True
    assert health[-1] is True
    with pytest.raises(SpoolNotFound, match="Spool 999 not found"):
        await client.get_spool(999)
    assert sim.requests[0] == ("GET", "/api/v1/spool/97", None)


async def test_measure_updates_used_weight(spoolman) -> None:  # noqa: ANN001
    sim, client, _ = spoolman
    result = await client.measure(97, 984.0)
    assert result.dry_run is False
    assert result.spool["used_weight"] == pytest.approx(1000 + 180 - 984)
    assert result.spool["remaining_weight"] == pytest.approx(804.0)
    result = await client.measure(97, 1300.0)
    assert result.spool["initial_weight"] == 1300.0 - 180.0
    assert result.spool["used_weight"] == 0
    result = await client.measure(84, 557.0)
    assert result.spool["used_weight"] == pytest.approx(1000 + 157 - 557)
    assert result.spool["remaining_weight"] == pytest.approx(400.0)
    assert sim.requests[-1] == ("PUT", "/api/v1/spool/84/measure", {"weight": 557.0})


async def test_measure_without_initial_weight_is_an_error(spoolman) -> None:  # noqa: ANN001
    _, client, _ = spoolman
    with pytest.raises(SpoolmanError, match="Initial weight is not set") as info:
        await client.measure(100, 600.0)
    assert info.value.status == 400


async def test_patch_and_remaining_weight(spoolman) -> None:  # noqa: ANN001
    _, client, _ = spoolman
    result = await client.patch(97, {"spool_weight": 182.0, "remaining_weight": 0, "archived": True})
    assert result.spool["used_weight"] == 1000.0
    assert result.spool["remaining_weight"] == 0.0
    assert result.spool["archived"] is True
    restored = await client.patch(97, {"spool_weight": 180.0, "used_weight": 545.3, "archived": False})
    assert restored.spool["remaining_weight"] == pytest.approx(454.7)
    with pytest.raises(SpoolmanError, match="both used and remaining"):
        await client.patch(97, {"used_weight": 1, "remaining_weight": 1})


async def test_writes_off_is_a_dry_run(spoolman) -> None:  # noqa: ANN001
    sim, client, _ = spoolman
    client.writes = False
    before = len(sim.requests)
    assert (await client.measure(97, 984.0)).dry_run is True
    assert (await client.patch(97, {"archived": True})).dry_run is True
    with pytest.raises(SpoolmanError, match="writes are off"):
        await client._request("PUT", "/spool/97/measure", {"weight": 1})  # noqa: SLF001
    assert len(sim.requests) == before
    assert sim.spools[97]["archived"] is False
    assert (await client.get_spool(97))["id"] == 97


async def test_offline_and_unreachable(spoolman) -> None:  # noqa: ANN001
    sim, client, health = spoolman
    sim.online = False
    with pytest.raises(SpoolmanError, match="503"):
        await client.get_spool(97)
    assert health[-1] is False
    assert await client.health() is False
    async with aiohttp.ClientSession() as session:
        dead = SpoolmanClient("http://127.0.0.1:9/api/v1", session, writes=True, timeout=0.5,
                              on_health=health.append)
        with pytest.raises(SpoolmanError, match="unreachable"):
            await dead.get_spool(1)
    assert health[-1] is False


def test_spool_info_mapping() -> None:
    spools = {spool["id"]: spool for spool in load_spool_fixtures()}
    info = spool_info_from_api(spools[97], low_stock_g=100)
    assert (info.vendor, info.name, info.material, info.color) == ("Sunlu", "ABS White", "ABS", "#FFFFFF")
    assert (info.remaining_g, info.spool_weight_g, info.expected_gross_g) == (454.7, 180.0, 634.7)
    assert info.tare_source == "spool"
    assert info.low_stock is False
    assert info.location == "Dry box A"
    low = spool_info_from_api(spools[86], low_stock_g=100)
    assert low.low_stock is True
    assert low.tare_source == "spool" or low.tare_source == "filament"
    vendor_tare = spool_info_from_api(spools[92], low_stock_g=100)
    assert (vendor_tare.spool_weight_g, vendor_tare.tare_source) == (250.0, "vendor")
    unknown = spool_info_from_api(spools[99], low_stock_g=100)
    assert unknown.spool_weight_g is None and unknown.expected_gross_g is None
    assert spool_info_from_api(spools[60], low_stock_g=100).archived is True
    assert spool_info_from_api(spools[93], low_stock_g=100).color == "#C94CE0"


def test_tare_and_color_helpers() -> None:
    assert spool_tare({"spool_weight": 0, "filament": {"spool_weight": 100}}) == (0.0, "spool")
    assert spool_tare({"filament": {"vendor": {"empty_spool_weight": None}}}) == (None, None)
    assert spool_color({"color_hex": "ff00aa"}) == "#FF00AA"
    assert spool_color({"color_hex": ""}) is None
