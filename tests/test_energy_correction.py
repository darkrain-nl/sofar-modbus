"""Torn-read correction for the energy counters' TOTAL_INCREASING fields."""

from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter


async def test_a_small_dip_holds_at_the_high_water_mark(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.async_update()
    assert hybrid.energy.corrected("solar_generation_total") == pytest.approx(10000.0)

    mock_modbus_unit.holding[0x0686] = [0x0001, 0x869B]  # 9999.5 kWh: a torn read
    await hybrid.async_update()

    assert hybrid.energy.solar_generation_total == pytest.approx(9999.5)  # raw
    assert hybrid.energy.corrected("solar_generation_total") == pytest.approx(10000.0)


async def test_a_genuine_reset_passes_through(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.async_update()
    assert hybrid.energy.corrected("solar_generation_today") == pytest.approx(12.34)

    mock_modbus_unit.holding[0x0684] = [0, 0]  # midnight reset
    await hybrid.async_update()

    assert hybrid.energy.solar_generation_today == pytest.approx(0.0)
    assert hybrid.energy.corrected("solar_generation_today") == pytest.approx(0.0)


async def test_seeding_the_high_water_mark_protects_the_first_poll(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    hybrid.energy.seed_high_water("solar_generation_total", 10005.0)
    mock_modbus_unit.holding[0x0686] = [0x0001, 0x869B]  # 9999.5 kWh: a torn read

    await hybrid.async_update()

    assert hybrid.energy.corrected("solar_generation_total") == pytest.approx(10005.0)


def test_corrected_is_none_before_the_first_poll(hybrid: SofarInverter) -> None:
    assert hybrid.energy.corrected("solar_generation_total") is None
