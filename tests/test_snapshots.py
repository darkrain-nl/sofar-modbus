"""Pin every decoded field and every read, per inverter family."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from modbus_connection.mock import MockModbusUnit
from modbus_connection.model import Component
from syrupy.assertion import SnapshotAssertion

from sofar_modbus import SofarInverter
from sofar_modbus.modern.battery import BatteryString
from sofar_modbus.modern.pv import PvString

FIXTURES = Path(__file__).parent / "fixtures"


def decoded(component: Component) -> dict[str, Any]:
    """Each field's value, keyed by its name and absolute address."""
    return {
        f"{name} @ 0x{resolved.address:04X}": resolved.field.__get__(component)
        for name, resolved in component.resolved_fields.items()
    }


def take_reads(unit: MockModbusUnit) -> list[str]:
    """The reads since the last call, in the order they were sent."""
    reads = [
        f"{event.register_type} 0x{event.address:04X} +{event.count}"
        for event in unit.read_events
    ]
    unit.read_events.clear()
    return reads


def pv_values(string: PvString) -> tuple[float | None, ...]:
    """What the PV string view reports."""
    return (string.voltage, string.current, string.power)


def battery_values(string: BatteryString) -> tuple[float | None, ...]:
    """What the battery string view reports."""
    return (
        string.voltage,
        string.current,
        string.power,
        string.temperature,
        string.capacity,
        string.state_of_health,
        string.charge_cycle,
    )


def modern_components(inverter: SofarInverter) -> dict[str, Component]:
    """Every component a modern inverter can poll, by its public name."""
    return {
        "state": inverter.state,
        "grid": inverter.grid,
        "offgrid": inverter.offgrid,
        "offgrid_single_phase": inverter.offgrid_single_phase,
        "offgrid_three_phase": inverter.offgrid_three_phase,
        "pv_1_2": inverter.pv_1_2,
        "pv_3": inverter.pv_3,
        "pv_4": inverter.pv_4,
        "pv_5_6": inverter.pv_5_6,
        "pv_7_8": inverter.pv_7_8,
        "pv_9_10": inverter.pv_9_10,
        "battery_1_2": inverter.battery_1_2,
        "battery_3_8": inverter.battery_3_8,
        "battery_totals": inverter.battery_totals,
        "energy": inverter.energy,
        "meter_energy": inverter.meter_energy,
        "battery_energy": inverter.battery_energy,
        "fault_log": inverter.fault_log,
        "rtc_sync": inverter.rtc_sync,
        "feed_in": inverter.feed_in,
        "eps": inverter.eps,
        "battery_active_control": inverter.battery_active_control,
        "parallel": inverter.parallel,
        "battery_config_id": inverter.battery_config_id,
        "battery_config": inverter.battery_config,
        "battery_charge_cutoff": inverter.battery_charge_cutoff,
        "remote": inverter.remote,
        "active_power_control": inverter.active_power_control,
        "charger": inverter.charger,
        "passive": inverter.passive,
    }


async def modern_snapshot(
    inverter: SofarInverter, unit: MockModbusUnit, pv_strings: range
) -> dict[str, Any]:
    """Run every read step, recording what each one sent."""
    await inverter.async_update()
    setup_reads = take_reads(unit)
    await inverter.async_update()
    poll_reads = take_reads(unit)
    await inverter.async_read_identity()
    identity_reads = take_reads(unit)
    await inverter.async_update_packs()
    components = modern_components(inverter)
    return {
        "model": inverter.model,
        "type": inverter.inverter_type,
        "setup reads": setup_reads,
        "poll reads": poll_reads,
        "identity reads": identity_reads,
        "pack reads": take_reads(unit),
        "readings": {
            name: decoded(components[name]) for name in inverter.readings_components
        },
        "settings": {
            name: decoded(components[name]) for name in inverter.settings_components
        },
        "identity": decoded(inverter.identity),
        "rating": decoded(inverter.rating),
        "packs": {
            place: decoded(pack) for place, pack in inverter.battery_packs.items()
        },
        "active faults": sorted(
            inverter.state.active_faults, key=lambda fault: fault.id
        ),
        "clock": inverter.identity.rtc,
        "fault log": inverter.fault_log.entries,
        "pv strings": {
            number: pv_values(inverter.pv_string(number)) for number in pv_strings
        },
        "battery strings": {
            number: battery_values(inverter.battery_string(number))
            for number in sorted(inverter.wired_battery_strings)
        },
        "pack cells": {
            place: (pack.cell_voltages, pack.cell_temperatures, pack.pack_time)
            for place, pack in inverter.battery_packs.items()
        },
    }


async def test_hybrid(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    snapshot: SnapshotAssertion,
) -> None:
    """A seeded three-phase hybrid with a three-group BTS tower."""
    assert await modern_snapshot(hybrid, mock_modbus_unit, range(1, 3)) == snapshot


@pytest.mark.parametrize(
    ("capture", "pv_strings"),
    [("ktlx_g3_4_4", range(1, 3)), ("esi_10k_t1", range(1, 4))],
)
async def test_replayed_capture(
    mock_modbus_unit: MockModbusUnit,
    snapshot: SnapshotAssertion,
    capture: str,
    pv_strings: range,
) -> None:
    """A real inverter's registers and masks, replayed through the mock."""
    data = json.loads((FIXTURES / f"{capture}.json").read_text())
    mock_modbus_unit.load_raw(data["raw"])
    for base, mask in data["address_masks"].items():
        mock_modbus_unit.holding[int(base)] = [
            mask >> shift & 0xFFFF for shift in (48, 32, 16, 0)
        ]
    inverter = await SofarInverter.async_detect(mock_modbus_unit)
    mock_modbus_unit.read_events.clear()
    assert await modern_snapshot(inverter, mock_modbus_unit, pv_strings) == snapshot
