"""One failing block never drags the rest of the poll down."""

from __future__ import annotations

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter, SofarLegacyInverter

from .conftest import ascii_words


async def test_a_failed_component_leaves_the_rest_fresh(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.async_update()
    before = hybrid.grid.active_power_output_total

    mock_modbus_unit.holding[0x0485] = 4321  # grid power changes on the device
    mock_modbus_unit.holding[0x0684] = [0, 2000]  # so does solar generation
    mock_modbus_unit.fail_read(0x0484, ModbusTimeoutError("slow grid block"))
    report = await hybrid.async_update()

    assert not report.complete
    assert set(report.failed) == {"grid"}
    assert isinstance(report.failed["grid"], ModbusTimeoutError)
    assert "energy" in report.updated
    assert hybrid.grid.active_power_output_total == before
    assert hybrid.energy.solar_generation_today == 20.0


async def test_listeners_fire_at_the_end_and_only_for_fresh_components(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.async_update()
    seen: list[int] = []
    hybrid.energy.add_update_listener(
        lambda: seen.append(len(mock_modbus_unit.read_events))
    )
    hybrid.grid.add_update_listener(lambda: seen.append(-1))

    mock_modbus_unit.fail_read(0x0484, ModbusTimeoutError("slow grid block"))
    mock_modbus_unit.read_events.clear()
    await hybrid.async_update()

    # One notification after the whole poll; none for the failure.
    assert seen == [len(mock_modbus_unit.read_events)]


async def test_a_dead_link_raises_instead_of_reporting(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.async_update()
    mock_modbus_unit.fail_requests(ModbusConnectionError("link down"))
    with pytest.raises(ModbusConnectionError):
        await hybrid.async_update()


async def test_every_component_refreshes_on_a_healthy_device(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    report = await hybrid.async_update()
    assert report.complete
    assert report.failed == {}
    assert {"state", "grid", "energy", "battery_totals"} <= report.updated
    assert "battery_pack" not in report.updated


async def test_legacy_containment_matches_the_modern_contract(
    legacy_hybrid: SofarLegacyInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await legacy_hybrid.async_update()

    mock_modbus_unit.holding[0x0210] = 80  # battery capacity changes
    mock_modbus_unit.fail_read(0x0250, ModbusTimeoutError("slow PV block"))
    report = await legacy_hybrid.async_update()

    assert set(report.failed) == {"hybrid_pv_1"}
    assert legacy_hybrid.storage.battery_capacity_charge == 80
    assert legacy_hybrid.hybrid_pv_1.pv_power_1 == 3000.0  # previous value kept


async def test_a_failed_setup_still_raises(mock_modbus_unit: MockModbusUnit) -> None:
    """Identity is the poll's foundation; without it there is nothing partial."""
    mock_modbus_unit.holding[0x0445] = ascii_words("SP1ES12345678", 7)
    mock_modbus_unit.fail_read(0x0445, ModbusTimeoutError("no serial"))
    inverter = SofarInverter(mock_modbus_unit)
    with pytest.raises(ModbusTimeoutError):
        await inverter.async_update()


async def test_a_timeout_with_nothing_answered_is_fatal(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A silent inverter must cost one timeout, not one per component."""
    await hybrid.async_update()

    mock_modbus_unit.fail_read(0x0404, ModbusTimeoutError("inverter asleep"))
    mock_modbus_unit.read_events.clear()
    with pytest.raises(ModbusTimeoutError):
        await hybrid.async_update()

    # The first component is the probe; the poll gives up, not walks on.
    assert len(mock_modbus_unit.read_events) == 1


async def test_a_refusal_on_the_first_component_is_still_contained(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """An exception response proves the inverter is there, so the poll goes on."""
    await hybrid.async_update()

    mock_modbus_unit.fail_read(0x0404, IllegalDataAddressError())
    report = await hybrid.async_update()

    assert set(report.failed) == {"state"}
    assert "grid" in report.updated


async def test_legacy_fatal_timeout_matches_the_modern_contract(
    legacy_hybrid: SofarLegacyInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await legacy_hybrid.async_update()

    mock_modbus_unit.fail_read(0x0200, ModbusTimeoutError("inverter asleep"))
    mock_modbus_unit.read_events.clear()
    with pytest.raises(ModbusTimeoutError):
        await legacy_hybrid.async_update()

    assert len(mock_modbus_unit.read_events) == 1


async def test_a_settings_poll_alone_gives_up_on_a_silent_inverter(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Nothing answered yet is per-poll: a settings poll pays one timeout."""
    await hybrid.async_update()

    mock_modbus_unit.fail_read(0x100A, ModbusTimeoutError("inverter asleep"))
    mock_modbus_unit.read_events.clear()
    with pytest.raises(ModbusTimeoutError):
        await hybrid.async_update_settings()

    assert len(mock_modbus_unit.read_events) == 1


async def test_the_same_timeout_inside_a_full_update_is_contained(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The readings already answered, so the inverter is not silent after all."""
    await hybrid.async_update()

    mock_modbus_unit.fail_read(0x100A, ModbusTimeoutError("slow rtc_sync block"))
    report = await hybrid.async_update()

    assert set(report.failed) == {"rtc_sync"}
    assert "state" in report.updated
