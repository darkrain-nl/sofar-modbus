"""The semantic fault layer: vendor IDs, subsystems, and what's active now."""

from __future__ import annotations

import collections

from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter
from sofar_modbus.modern import (
    FAULTS,
    FAULTS_BY_ID,
    Fault1,
    Fault5,
    Fault11,
    FaultCategory,
)
from sofar_modbus.modern.inverter import _REGISTER_FAULTS


def test_table_is_complete() -> None:
    # 355 bits in the register enums, less ID464/ID480 vendor filler.
    assert len(FAULTS) == 353
    assert len({fault.id for fault in FAULTS}) == 353
    assert len({fault.key for fault in FAULTS}) == 353
    assert FAULTS_BY_ID == {fault.id: fault for fault in FAULTS}
    assert len(FaultCategory) == 17


def test_categories_hold_the_bits_they_were_assigned() -> None:
    # The vendor spec defines no categories, so each count is a choice.
    assert collections.Counter(fault.category for fault in FAULTS) == {
        FaultCategory.COMBINER_BOX: 96,
        FaultCategory.INTERNAL: 42,
        FaultCategory.ARC_FAULT: 34,
        FaultCategory.STRING_FUSE: 32,
        FaultCategory.BATTERY: 24,
        FaultCategory.GRID: 20,
        FaultCategory.INPUT_FUSE: 16,
        FaultCategory.PV: 14,
        FaultCategory.THERMAL: 14,
        FaultCategory.DC_BUS: 14,
        FaultCategory.COMMUNICATION: 12,
        FaultCategory.AC_OUTPUT: 10,
        FaultCategory.FAN: 7,
        FaultCategory.DERATING: 6,
        FaultCategory.INSULATION: 4,
        FaultCategory.BATTERY_PACK: 4,
        FaultCategory.SHUTDOWN: 4,
    }


def test_every_fault_is_reachable_from_exactly_one_bit() -> None:
    mapped = [fault for bits in _REGISTER_FAULTS.values() for fault in bits.values()]
    assert len(mapped) == 353
    assert set(mapped) == set(FAULTS)


def test_the_same_bit_in_two_registers_stays_distinct() -> None:
    # IntFlag members hash by value, so these two collide in any lookup that
    # isn't keyed by register number first.
    assert len({Fault1.ID001_GRID_OVER_VOLTAGE, Fault11.ID161_FORCED_SHUTDOWN}) == 1
    assert _REGISTER_FAULTS[1][1].key == "grid_over_voltage"
    assert _REGISTER_FAULTS[11][1].key == "forced_shutdown"


async def test_active_faults_span_subsystems(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    mock_modbus_unit.holding[0x0409] = 0  # clear the fixture's PV/battery bits
    mock_modbus_unit.holding[0x0411] = 0  # clear the fixture's string fuse bit
    mock_modbus_unit.holding[0x0432] = 0  # clear the fixture's combiner bit
    mock_modbus_unit.holding[0x043D] = 0  # clear the fixture's DCDC bit
    mock_modbus_unit.holding[0x0405] = 0x0001  # ID001 grid over-voltage
    # ID161 forced shutdown and ID169 fan 1, sharing register 0x040F.
    mock_modbus_unit.holding[0x040F] = 0x0001 | 0x0100
    mock_modbus_unit.holding[0x0410] = 0x0004  # ID179 BMS high temperature
    await hybrid.async_update()

    assert {(fault.key, fault.category) for fault in hybrid.state.active_faults} == {
        ("grid_over_voltage", FaultCategory.GRID),
        ("forced_shutdown", FaultCategory.SHUTDOWN),
        ("fan_1_fault", FaultCategory.FAN),
        ("bms_high_temperature_protection", FaultCategory.BATTERY),
    }


async def test_active_faults_are_empty_before_the_first_poll(
    hybrid: SofarInverter,
) -> None:
    assert hybrid.state.fault_5 is None
    assert hybrid.state.active_faults == frozenset()


async def test_no_faults_when_every_register_reads_clean(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    for address in (0x0409, 0x0411, 0x0432, 0x043D):
        mock_modbus_unit.holding[address] = 0
    await hybrid.async_update()

    assert hybrid.state.fault_5 == Fault5(0)
    assert hybrid.state.active_faults == frozenset()
