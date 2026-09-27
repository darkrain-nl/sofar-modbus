"""Typed accessors for per-string readings, corrected totals and writes."""

from __future__ import annotations

from typing import assert_type

import pytest
from modbus_connection.mock import MockModbusUnit, WriteEvent

from sofar_modbus import CorrectedTotal, SofarInverter
from sofar_modbus.modern import (
    BATTERY_STRING_COMPONENTS,
    PV_STRING_COMPONENTS,
    BatteryEnergy,
    ChargerUseMode,
    EnergyTotals,
    MeterEnergy,
    RemoteSwitchOnOff,
)

_PV_FIELDS = ("voltage", "current", "power")
_BATTERY_FIELDS = (
    "voltage",
    "current",
    "power",
    "temperature",
    "capacity",
    "state_of_health",
    "charge_cycle",
)


def test_valid_string_numbers() -> None:
    assert list(PV_STRING_COMPONENTS) == list(range(1, 11))
    assert list(BATTERY_STRING_COMPONENTS) == list(range(1, 9))


@pytest.fixture
def distinct_strings(mock_modbus_unit: MockModbusUnit) -> None:
    """Give every PV and battery string register a value of its own."""
    for address in (*range(0x0584, 0x05A2), *range(0x0604, 0x063C)):
        mock_modbus_unit.holding[address] = address - 0x0500


@pytest.mark.usefixtures("distinct_strings")
@pytest.mark.parametrize("number", range(1, 11))
async def test_pv_string_reads_its_own_fields(
    hybrid: SofarInverter, number: int
) -> None:
    string = hybrid.pv_string(number)
    await string.component.async_update()
    assert string.number == number
    assert string.component is getattr(hybrid, string.component_name)
    assert string.component_name == PV_STRING_COMPONENTS[number]
    for measurement in _PV_FIELDS:
        flat = getattr(string.component, f"pv_{measurement}_{number}")
        assert flat is not None
        assert getattr(string, measurement) == flat


@pytest.mark.usefixtures("distinct_strings")
@pytest.mark.parametrize("number", range(1, 9))
async def test_battery_string_reads_its_own_fields(
    hybrid: SofarInverter, number: int
) -> None:
    string = hybrid.battery_string(number)
    await string.component.async_update()
    assert string.number == number
    assert string.component is getattr(hybrid, string.component_name)
    assert string.component_name == BATTERY_STRING_COMPONENTS[number]
    for measurement in _BATTERY_FIELDS:
        flat = getattr(string.component, f"battery_{measurement}_{number}")
        assert flat is not None
        assert getattr(string, measurement) == flat


async def test_string_views_follow_the_poll(hybrid: SofarInverter) -> None:
    string = hybrid.pv_string(1)
    assert string.voltage is None
    await hybrid.async_update()
    assert string.voltage == pytest.approx(380.5)
    assert hybrid.battery_string(1).current == pytest.approx(-10.0)


@pytest.mark.parametrize("number", [0, 11, -1])
def test_pv_string_out_of_range_raises(hybrid: SofarInverter, number: int) -> None:
    with pytest.raises(ValueError, match=f"no PV string {number}"):
        hybrid.pv_string(number)


@pytest.mark.parametrize("number", [0, 9])
def test_battery_string_out_of_range_raises(hybrid: SofarInverter, number: int) -> None:
    with pytest.raises(ValueError, match=f"no battery string {number}"):
        hybrid.battery_string(number)


def test_every_total_has_a_handle() -> None:
    assert EnergyTotals._total_increasing_fields == (
        "solar_generation_today",
        "solar_generation_total",
    )
    assert MeterEnergy._total_increasing_fields == (
        "load_consumption_today",
        "load_consumption_total",
        "import_energy_today",
        "import_energy_total",
        "export_energy_today",
        "export_energy_total",
    )
    assert BatteryEnergy._total_increasing_fields == (
        "battery_input_energy_today",
        "battery_input_energy_total",
        "battery_output_energy_today",
        "battery_output_energy_total",
    )


async def test_total_handle_reads_and_seeds(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    total = hybrid.energy.solar_generation_total_corrected
    assert total.component is hybrid.energy
    assert total.name == "solar_generation_total"
    assert total.value is None

    total.seed(10005.0)
    mock_modbus_unit.holding[0x0686] = [0x0001, 0x869B]  # 9999.5 kWh: a torn read
    await hybrid.async_update()

    assert total.value == pytest.approx(10005.0)
    assert hybrid.energy.corrected("solar_generation_total") == total.value


async def test_write_charger_mode_typed(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.charger.async_write_mode(ChargerUseMode.PASSIVE_MODE)
    assert [(e.address, e.values, e.function_code) for e in events] == [
        (0x1110, [3], 0x10)
    ]


async def test_write_remote_switch_typed(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.remote.async_write_switch(RemoteSwitchOnOff.OFF)
    assert [(e.address, e.values, e.function_code) for e in events] == [
        (0x1104, [0], 0x10)
    ]


# mypy checks the rest; an unused ignore fails it under strict mode.
def test_accessor_types(hybrid: SofarInverter) -> None:
    pv = hybrid.pv_string(1)
    assert_type(pv.component_name, str)
    assert_type(pv.voltage, float | None)
    assert_type(pv.current, float | None)
    assert_type(pv.power, float | None)
    battery = hybrid.battery_string(1)
    assert_type(battery.component_name, str)
    assert_type(battery.voltage, float | None)
    assert_type(battery.current, float | None)
    assert_type(battery.power, float | None)
    assert_type(battery.temperature, int | None)
    assert_type(battery.capacity, int | None)
    assert_type(battery.state_of_health, int | None)
    assert_type(battery.charge_cycle, int | None)
    total = hybrid.meter_energy.import_energy_total_corrected
    assert_type(total, CorrectedTotal)
    assert_type(total.value, float | None)
    with pytest.raises(AttributeError):
        hybrid.energy.solar_generaton_total_corrected  # type: ignore[attr-defined]  # noqa: B018
    with pytest.raises(AttributeError):
        hybrid.energy.import_energy_total_corrected  # type: ignore[attr-defined]  # noqa: B018
