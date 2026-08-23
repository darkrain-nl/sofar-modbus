"""The older register map, decoded over the mock backend."""

from __future__ import annotations

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    IllegalFunctionError,
    ServerDeviceFailureError,
)
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarLegacyInverter
from sofar_modbus.legacy import PvRunMode, StorageRunMode, identify
from sofar_modbus.variants import AC, EPS, HYBRID, PV, X1, X3, InverterType

from .conftest import (
    LEGACY_HOLDING,
    LEGACY_HYBRID_SERIAL,
    LEGACY_THREE_PHASE_PV_SERIAL,
    ascii_words,
)


def test_identify_maps_serial_prefixes() -> None:
    assert identify("SM1E1234") == HYBRID | X1
    assert identify("SM1X1234") == PV  # SM1 without the E is the PV family
    assert identify("SC1E1234") == PV | X3
    assert identify("SA1abcd") == PV | X1
    assert identify("WHAT") == InverterType(0)


async def test_setup_strips_the_padding_the_boards_add(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """The plugin runs the serial through a character filter; so do we."""
    mock_modbus_unit.input[0x2002] = ascii_words("SM1E\x01234567\x02", 6)
    inverter = SofarLegacyInverter(mock_modbus_unit)
    await inverter._async_setup()
    assert inverter.serial_number == "SM1E234567"
    # A hybrid always gets probed; the mock answers 0 for unset registers.
    assert inverter.inverter_type == HYBRID | X1 | EPS


async def test_storage_registers(legacy_hybrid: SofarLegacyInverter) -> None:
    await legacy_hybrid.async_update()
    storage = legacy_hybrid.storage
    assert storage.run_mode is StorageRunMode.NORMAL_MODE
    assert storage.voltage_r == pytest.approx(230.2)
    assert storage.battery_power_charge == pytest.approx(-20.0)  # signed
    assert storage.battery_voltage_charge == pytest.approx(51.2)
    assert storage.battery_capacity_charge == 76
    assert storage.measured_power == pytest.approx(-2.0)
    assert storage.house_load == pytest.approx(3.5)
    assert storage.generation_total == 4321  # uint32
    assert storage.generation_time_today == 315


async def test_the_values_the_plugin_computes_are_properties(
    legacy_hybrid: SofarLegacyInverter,
) -> None:
    """Upstream derives these in Home Assistant; they have no register."""
    await legacy_hybrid.async_update()
    storage = legacy_hybrid.storage
    assert storage.battery_output_energy == pytest.approx(20.0)  # discharging
    assert storage.battery_input_energy == pytest.approx(0.0)
    assert storage.grid_import == pytest.approx(2.0)  # measured power is negative
    assert storage.grid_export == pytest.approx(0.0)
    assert legacy_hybrid.pv_power_total == pytest.approx(3000 + 2500)


async def test_hybrid_pv_strings(legacy_hybrid: SofarLegacyInverter) -> None:
    await legacy_hybrid.async_update()
    # Upstream's key for the voltage is misspelled; it is kept as declared.
    assert legacy_hybrid.hybrid_pv_1.pv_oltage_1 == pytest.approx(380.1)
    assert legacy_hybrid.hybrid_pv_1.pv_current_1 == pytest.approx(8.0)
    assert legacy_hybrid.hybrid_pv_1.pv_power_1 == pytest.approx(3000)  # raw * 10
    assert legacy_hybrid.hybrid_pv_2.pv_oltage_2 == pytest.approx(370.2)
    assert legacy_hybrid.hybrid_pv_2.pv_power_2 == pytest.approx(2500)


async def test_a_single_phase_storage_inverter_skips_the_s_and_t_phases(
    legacy_hybrid: SofarLegacyInverter,
) -> None:
    report = await legacy_hybrid.async_update()
    assert "storage_three_phase" not in report.updated
    assert legacy_hybrid.storage_three_phase.voltage_s is None
    assert legacy_hybrid.storage.voltage_r is not None


async def test_the_eps_probe_detects_presence(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """A hybrid inverter that answers the EPS registers gets EPS set."""
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    mock_modbus_unit.input[0x2002] = ascii_words(LEGACY_HYBRID_SERIAL, 6)
    inverter = SofarLegacyInverter(mock_modbus_unit)
    await inverter.async_update()
    assert inverter.storage_eps.eps_voltage == pytest.approx(228.0)
    assert EPS in (inverter.inverter_type or InverterType(0))


@pytest.mark.parametrize("error", [IllegalDataAddressError(), IllegalFunctionError()])
async def test_the_eps_probe_detects_absence(
    mock_modbus_unit: MockModbusUnit, error: Exception
) -> None:
    """Either exception code means the EPS registers do not exist."""
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    mock_modbus_unit.input[0x2002] = ascii_words(LEGACY_HYBRID_SERIAL, 6)
    mock_modbus_unit.fail_read(0x0216, error)
    inverter = SofarLegacyInverter(mock_modbus_unit)
    await inverter.async_update()
    assert inverter.storage_eps.eps_voltage is None
    assert EPS not in (inverter.inverter_type or InverterType(0))


async def test_the_eps_probe_is_skipped_for_a_pv_only_inverter(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """A PV-only inverter can never have EPS, so it is never probed."""
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    mock_modbus_unit.input[0x2002] = ascii_words(LEGACY_THREE_PHASE_PV_SERIAL, 6)
    inverter = SofarLegacyInverter(mock_modbus_unit)
    await inverter.async_update()
    assert not any(e.address == 0x0216 for e in mock_modbus_unit.read_events)


async def test_a_probe_failure_other_than_absence_propagates(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """A real device error is not mistaken for "no EPS" and swallowed."""
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    mock_modbus_unit.input[0x2002] = ascii_words(LEGACY_HYBRID_SERIAL, 6)
    mock_modbus_unit.fail_read(0x0216, ServerDeviceFailureError())
    inverter = SofarLegacyInverter(mock_modbus_unit)
    with pytest.raises(ServerDeviceFailureError):
        await inverter.async_update()
    assert inverter._polled is None  # setup did not complete; retry next time


async def test_three_phase_pv(legacy_three_phase_pv: SofarLegacyInverter) -> None:
    report = await legacy_three_phase_pv.async_update()
    assert legacy_three_phase_pv.inverter_type == PV | X3
    pv = legacy_three_phase_pv.pv_three_phase
    assert pv.pv_voltage_2 == pytest.approx(371.2)
    assert pv.pv_power_1 == pytest.approx(2.5)
    assert pv.activepower == pytest.approx(4.8)
    assert pv.voltage_r == pytest.approx(230.1)
    assert pv.current_r == pytest.approx(10.5)
    assert pv.voltage_s == pytest.approx(229.9)
    assert pv.total_production == 5000  # uint32
    assert pv.bus_voltage == pytest.approx(650.1)
    assert pv.inverter_heatsink_temperature == 41
    # Storage registers belong to another inverter type.
    assert "storage" not in report.updated


async def test_current_r_and_voltage_s_addresses(
    legacy_three_phase_pv: SofarLegacyInverter,
) -> None:
    """Current R is at 0x0013 and Voltage S is at 0x0014."""
    await legacy_three_phase_pv.async_update()
    pv = legacy_three_phase_pv.pv_three_phase
    assert pv.declared_fields["current_r"].address == 0x0013
    assert pv.declared_fields["voltage_s"].address == 0x0014
    assert pv.current_r == pytest.approx(10.5)
    assert pv.voltage_s == pytest.approx(229.9)


async def test_the_pv_only_component_applies_to_both_phase_counts(
    legacy_three_phase_pv: SofarLegacyInverter,
) -> None:
    """Upstream marks these ``PV`` with no phase bit, so both variants read them.

    On a three-phase inverter that means 0x001B/0x001C are read *as well as* the
    three-phase temperatures at 0x001E/0x001F, and the two disagree. Both are
    kept, on their own components, rather than one silently winning — the two
    pool into one read, but each keeps its own field.
    """
    report = await legacy_three_phase_pv.async_update()
    assert "pv_block" in report.updated
    assert legacy_three_phase_pv.pv_common.run_mode is PvRunMode.NORMAL_MODE
    assert (
        legacy_three_phase_pv.pv_common.declared_fields[
            "inverter_heatsink_temperature"
        ].address
        == 0x001B
    )
    assert (
        legacy_three_phase_pv.pv_three_phase.declared_fields[
            "inverter_heatsink_temperature"
        ].address
        == 0x001E
    )


async def test_an_ac_coupled_inverter_reads_the_input_register_setting(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """``battery_minimum_capacity`` is AC-only, and in the input space."""
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    mock_modbus_unit.input[0x2002] = ascii_words(LEGACY_THREE_PHASE_PV_SERIAL, 6)
    mock_modbus_unit.input[0x104D] = 20
    inverter = SofarLegacyInverter(mock_modbus_unit, inverter_type=AC | X1)
    await inverter.async_update()
    assert inverter.battery_settings.battery_minimum_capacity == 20
    assert inverter.storage.run_mode is StorageRunMode.NORMAL_MODE


async def test_constructor_identity_skips_serial_number_read(
    legacy_hybrid: SofarLegacyInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Identity given to the constructor still gets probed for EPS."""
    await legacy_hybrid.async_update()

    mock_modbus_unit.read_events.clear()
    device = SofarLegacyInverter(
        mock_modbus_unit,
        serial_number=LEGACY_HYBRID_SERIAL,
        inverter_type=HYBRID | X1,
    )
    await device._async_setup()

    # The only read is the EPS probe; the serial number is never touched.
    assert [e.address for e in mock_modbus_unit.read_events] == [0x0216]
    assert device.serial_number == LEGACY_HYBRID_SERIAL
    assert device.inverter_type == legacy_hybrid.inverter_type
