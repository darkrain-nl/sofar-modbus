"""The current-generation register map, decoded over the mock backend."""

from __future__ import annotations

from datetime import datetime

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    IllegalFunctionError,
    ServerDeviceFailureError,
)
from modbus_connection.mock import MockModbusUnit, WriteEvent

from sofar_modbus import SofarInverter
from sofar_modbus.modern import (
    ChargerUseMode,
    EpsControlMode,
    Fault1,
    Fault5,
    Fault13,
    Fault19,
    Fault30,
    FeedinLimitationMode,
    ParallelMasterslave,
    PassiveModeTimeoutAction,
    PowerControlFlags,
    RemoteSwitchOnOff,
    SyncRtcResult,
    SystemState,
    identify,
)
from sofar_modbus.variants import (
    BAT_BTS,
    EPS,
    GEN,
    HYBRID,
    MPPT10,
    PM,
    PV,
    X1,
    X3,
    InverterType,
)

from .conftest import HYBRID_SERIAL, MODERN_HOLDING, ascii_words


def test_identify_maps_serial_prefixes() -> None:
    assert identify("SP1ES120N6ABCD") == (HYBRID | X3, "HYD20KTL-3P")
    assert identify(HYBRID_SERIAL) == (HYBRID | X3 | GEN | BAT_BTS, "HYDxxKTL-3P")
    assert identify("SQ1ES1000001") == (PV | X3 | GEN | MPPT10, "100kW KTLX-G4")
    assert identify("SH3E000001") == (PV | X1 | GEN, "4.6 KTLM-G3")
    assert identify("SA1000001") == (PV | X1, None)
    assert identify("NOPE00001") == (0, None)


def test_the_longer_prefix_wins() -> None:
    """SP1ES120N6 is a plain HYD20KTL-3P, not the battery-tower SP1 family."""
    specific, _ = identify("SP1ES120N6ABCD")
    generic, _ = identify("SP1ES999999")
    assert BAT_BTS not in specific
    assert BAT_BTS in generic


async def test_setup_reads_the_serial_and_settles_the_model(
    hybrid: SofarInverter,
) -> None:
    await hybrid.async_update()
    assert hybrid.serial_number == HYBRID_SERIAL
    assert hybrid.model == "HYDxxKTL-3P"
    assert hybrid.inverter_type == HYBRID | X3 | GEN | BAT_BTS | EPS | PM
    assert hybrid.has_battery_tower is True


async def test_component_names_are_empty_until_setup(
    hybrid: SofarInverter,
) -> None:
    """Callers can see what a set-up inverter polls, per poll group."""
    assert hybrid.readings_components == ()
    assert hybrid.settings_components == ()

    await hybrid.async_update()

    assert "grid" in hybrid.readings_components
    assert "feed_in" in hybrid.settings_components
    assert not set(hybrid.readings_components) & set(hybrid.settings_components)


async def test_readings_and_settings_polls_are_disjoint(
    hybrid: SofarInverter,
) -> None:
    """The readings poll and settings poll touch separate components."""
    settings = await hybrid.async_update_settings()
    readings = await hybrid.async_update_readings()

    assert not (settings.updated & readings.updated)
    assert not (settings.updated & set(readings.failed))
    assert not (set(settings.failed) & readings.updated)


async def test_constructor_identity_skips_serial_number_read(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Identity given to the constructor still gets probed for EPS."""
    await hybrid.async_update()

    mock_modbus_unit.read_events.clear()
    device = SofarInverter(
        mock_modbus_unit,
        serial_number=HYBRID_SERIAL,
        model="HYDxxKTL-3P",
        inverter_type=HYBRID | X3 | GEN | BAT_BTS,
        read_pm=True,
    )
    await device._async_setup()

    # Rating and the EPS probe are read; the serial number is never touched.
    assert [e.address for e in mock_modbus_unit.read_events] == [0x06ED, 0x0504]
    assert device.serial_number == HYBRID_SERIAL
    assert device.model == "HYDxxKTL-3P"
    assert device.inverter_type == hybrid.inverter_type
    assert device._readings == hybrid._readings
    assert device._settings == hybrid._settings


async def test_state_and_faults(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.state.system_state is SystemState.GRID_CONNECTED
    assert hybrid.state.fault_1 == Fault1(0)  # 0 decodes to the empty flag
    assert (
        hybrid.state.fault_5
        == Fault5.ID069_PV_OVERVOLTAGE | Fault5.ID070_BATTERY_OVER_VOLTAGE
    )
    assert hybrid.state.fault_13 == Fault13.ID193_STRING_FUSE_OPEN_1_1
    assert hybrid.state.fault_19 == Fault19.ID289_COMBINER_OC_17
    assert hybrid.state.fault_20 == 7  # reserved, no bits assigned
    assert hybrid.state.fault_30 == Fault30.ID465_DCDC_FAULT
    assert hybrid.state.waiting_time == 30
    assert hybrid.state.inverter_temperature_1 == 45
    assert hybrid.state.heatsink_temperature_6 == 48
    assert hybrid.state.module_temperature_1 == -10  # signed
    assert hybrid.state.module_temperature_3 == 33
    assert hybrid.state.generation_time_today == 15
    assert hybrid.state.generation_time_total == 100
    assert hybrid.state.service_time_total == 200
    assert hybrid.state.insulation_resistance == 500


async def test_rated_power(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.rating.rated_power == pytest.approx(15.0)


async def test_rated_power_zero_is_unavailable(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A raw 0 is not a real nameplate rating; it decodes as unknown."""
    mock_modbus_unit.holding[0x06ED] = 0
    await hybrid.rating.async_update()
    assert hybrid.rating.rated_power is None


async def test_identity_and_clock(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.identity.serial_number == HYBRID_SERIAL
    assert hybrid.identity.hardware_version == "V1"
    assert hybrid.identity.software_version == "V210"
    assert hybrid.identity.rtc == datetime(2025, 8, 12, 14, 30, 5)


async def test_a_blank_clock_reads_as_no_value(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Month 0 is not a date; the property says so rather than raising."""
    mock_modbus_unit.holding[0x042D] = 0
    await hybrid.async_update()
    assert hybrid.identity.rtc is None


async def test_grid_output(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    grid = hybrid.grid
    assert grid.grid_frequency == pytest.approx(50.01)
    assert grid.active_power_output_total == pytest.approx(12.34)
    assert grid.reactive_power_output_total == pytest.approx(-1.0)  # signed
    assert grid.apparent_power_output_total == pytest.approx(12.5)
    assert grid.voltage_l1 == pytest.approx(230.1)
    assert grid.current_output_l1 == pytest.approx(5.43)
    assert grid.power_factor_output_l1 == pytest.approx(0.998)
    assert grid.voltage_line_l3 == pytest.approx(398.1)
    assert grid.active_power_pcc_total_wide == pytest.approx(2.0)
    assert grid.power_factor_output_total == pytest.approx(0.995)


async def test_the_eps_probe_detects_presence(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """A hybrid inverter that answers the off-grid block gets EPS set."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    inverter = SofarInverter(mock_modbus_unit)
    report = await inverter.async_update()
    assert inverter.offgrid.offgrid_frequency == pytest.approx(49.98)
    assert "offgrid" in report.updated
    assert EPS in (inverter.inverter_type or InverterType(0))


@pytest.mark.parametrize("error", [IllegalDataAddressError(), IllegalFunctionError()])
async def test_the_eps_probe_detects_absence(
    mock_modbus_unit: MockModbusUnit, error: Exception
) -> None:
    """Either exception code means the off-grid block does not exist."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.fail_read(0x0504, error)
    inverter = SofarInverter(mock_modbus_unit)
    report = await inverter.async_update()
    assert inverter.offgrid.offgrid_frequency is None
    assert "offgrid" not in report.updated
    assert EPS not in (inverter.inverter_type or InverterType(0))


async def test_the_eps_probe_is_skipped_for_a_pv_only_inverter(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """A PV-only inverter can never have EPS, so it is never probed."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    inverter = SofarInverter(mock_modbus_unit, inverter_type=PV | X1)
    await inverter.async_update()
    assert not any(e.address == 0x0504 for e in mock_modbus_unit.read_events)


async def test_a_probe_failure_other_than_absence_propagates(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """A real device error is not mistaken for "no EPS" and swallowed."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.fail_read(0x0504, ServerDeviceFailureError())
    inverter = SofarInverter(mock_modbus_unit)
    with pytest.raises(ServerDeviceFailureError):
        await inverter.async_update()
    assert inverter._readings is None  # setup did not complete; retry next time


async def test_off_grid_three_phase(hybrid: SofarInverter) -> None:
    report = await hybrid.async_update()
    assert hybrid.offgrid.offgrid_frequency == pytest.approx(49.98)
    assert hybrid.offgrid.active_power_offgrid_total == pytest.approx(3.0)
    assert hybrid.offgrid_three_phase.offgrid_voltage_l1 == pytest.approx(229.5)
    assert hybrid.offgrid_three_phase.offgrid_voltage_l2 == pytest.approx(228.8)
    # The single-phase layout overlaps the three-phase one at 0x050A;
    # only the component matching the phase count is polled.
    assert "offgrid_single_phase" not in report.updated
    assert hybrid.offgrid_single_phase.offgrid_voltage is None


async def test_pv_strings(hybrid: SofarInverter) -> None:
    report = await hybrid.async_update()
    assert hybrid.pv_1_2.pv_voltage_1 == pytest.approx(380.5)
    assert hybrid.pv_1_2.pv_current_1 == pytest.approx(8.12)
    assert hybrid.pv_1_2.pv_power_1 == pytest.approx(3.09)
    assert hybrid.pv_1_2.pv_voltage_2 == pytest.approx(371.2)
    assert hybrid.pv_1_2.pv_power_total == pytest.approx(5.8)
    # A two-MPPT inverter never reads strings 3 and up.
    assert "pv_3" not in report.updated
    assert hybrid.pv_3.pv_voltage_3 is None


async def test_extra_mppt_strings_appear_on_a_ten_mppt_inverter(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding[0x0445] = ascii_words("SQ1ES1000001", 7)
    mock_modbus_unit.holding[0x059F] = 3600  # PV voltage 10 -> 360.0 V
    inverter = SofarInverter(mock_modbus_unit)
    report = await inverter.async_update()
    assert inverter.model == "100kW KTLX-G4"
    for name in ("pv_3", "pv_4", "pv_5_6", "pv_7_8", "pv_9_10"):
        assert name in report.updated
    assert inverter.pv_9_10.pv_voltage_10 == pytest.approx(360.0)
    # PV-only: no battery, no hybrid-only settings.
    assert "battery_1_2" not in report.updated
    assert "charger" not in report.updated


async def test_battery_strings_and_totals(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.battery_1_2.battery_voltage_1 == pytest.approx(204.8)
    assert hybrid.battery_1_2.battery_current_1 == pytest.approx(-10.0)  # signed
    assert hybrid.battery_1_2.battery_power_1 == pytest.approx(-20.0)
    assert hybrid.battery_1_2.battery_capacity_1 == 87
    assert hybrid.battery_1_2.battery_charge_cycle_1 == 412
    assert hybrid.battery_1_2.battery_voltage_2 == pytest.approx(204.4)
    assert hybrid.battery_3_8.battery_voltage_3 == pytest.approx(204.0)
    assert hybrid.battery_totals.battery_power_total == pytest.approx(-6.0)
    assert hybrid.battery_totals.battery_capacity_total == 87
    assert hybrid.battery_totals.current_battery_num == 2


async def test_energy_counters(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.energy.solar_generation_today == pytest.approx(12.34)  # uint32
    assert hybrid.energy.solar_generation_total == pytest.approx(10000.0)
    assert hybrid.energy.load_consumption_today == pytest.approx(9.87)
    assert hybrid.battery_energy.battery_input_energy_today == pytest.approx(5.5)


async def test_settings(hybrid: SofarInverter) -> None:
    await hybrid.async_update()
    assert hybrid.rtc_sync.sync_rtc_result is SyncRtcResult.SUCCESSFUL
    assert (
        hybrid.feed_in.feedin_limitation_mode
        is FeedinLimitationMode.ENABLED_FEED_IN_LIMITATION
    )
    assert hybrid.feed_in.feedin_max_power == pytest.approx(5000)  # raw * 100
    assert hybrid.eps.eps_control is EpsControlMode.TURN_ON_ENABLE_COLD_START
    assert hybrid.battery_active_control.battery_active_control is True
    assert hybrid.parallel.parallel_control is True
    assert hybrid.parallel.parallel_masterslave is ParallelMasterslave.MASTER
    assert hybrid.parallel.parallel_address == 3
    assert hybrid.battery_config.bat_config_charging_voltage == pytest.approx(256.0)
    assert hybrid.remote.remote_switch_on_off is RemoteSwitchOnOff.ON
    assert hybrid.active_power_control.power_control is PowerControlFlags.ACTIVE_POWER
    assert hybrid.active_power_control.active_power_export_limit == pytest.approx(70.0)
    assert hybrid.charger.charger_use_mode is ChargerUseMode.TIME_OF_USE
    assert hybrid.passive.passive_mode_timeout == 600
    assert (
        hybrid.passive.passive_mode_timeout_action
        is PassiveModeTimeoutAction.RETURN_TO_PREVIOUS_MODE
    )
    assert hybrid.passive.passive_mode_grid_power == -2000  # int32
    assert hybrid.passive.passive_mode_battery_power_max == 3000


# --- writes ---------------------------------------------------------


async def test_write_charger_mode(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The mode register takes FC16 even though it is a single register."""
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.charger.write("charger_use_mode", ChargerUseMode.PASSIVE_MODE)
    assert [(e.address, e.values, e.function_code) for e in events] == [
        (0x1110, [3], 0x10)
    ]
    assert await mock_modbus_unit.read_holding_registers(0x1110, 1) == [3]


async def test_write_remote_switch(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.remote.write("remote_switch_on_off", RemoteSwitchOnOff.OFF)
    assert await mock_modbus_unit.read_holding_registers(0x1104, 1) == [0]


async def test_parallel_address_is_validated(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await hybrid.parallel.write("parallel_address", 7)
    assert await mock_modbus_unit.read_holding_registers(0x1037, 1) == [7]
    with pytest.raises(ValueError, match="outside 0-10"):
        await hybrid.parallel.write("parallel_address", 11)
    assert await mock_modbus_unit.read_holding_registers(0x1037, 1) == [7]  # unchanged


async def test_feed_in_limit_writes_both_registers(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.feed_in.async_write_limit(FeedinLimitationMode.DISABLED, 3000)
    assert [(e.address, e.values) for e in events] == [(0x1023, [0, 30])]
    with pytest.raises(ValueError, match="multiple of 100"):
        await hybrid.feed_in.async_write_limit(FeedinLimitationMode.DISABLED, 3050)


async def test_active_power_limit_writes_both_registers(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.active_power_control.async_write_active_power_limit(True, 30)
    await hybrid.active_power_control.async_write_active_power_limit(False, 80)
    assert [(e.address, e.values) for e in events] == [
        (0x1105, [int(PowerControlFlags.ACTIVE_POWER), 300]),
        (0x1105, [0, 800]),
    ]
    with pytest.raises(ValueError, match="outside 0-100"):
        await hybrid.active_power_control.async_write_active_power_limit(True, 101)


async def test_eps_control_writes_the_reserved_wait_time_as_zero(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.eps.async_write_control(EpsControlMode.TURN_OFF)
    assert [(e.address, e.values) for e in events] == [(0x1029, [0, 0])]


async def test_passive_mode_writes(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.passive.async_write_timeout(
        300, PassiveModeTimeoutAction.FORCE_STANDBY
    )
    await hybrid.passive.async_write_power(-2000, 0, 5000)
    assert [(e.address, e.values) for e in events] == [
        (0x1184, [300, 0]),
        # three signed 32-bit values, big-endian word order
        (0x1187, [0xFFFF, 0xF830, 0, 0, 0, 5000]),
    ]


async def test_set_time_writes_seven_registers(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The device requires a trailing constant 1 alongside the six date parts."""
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.async_set_time(datetime(2025, 8, 12, 14, 30, 5))
    assert [(e.address, e.values) for e in events] == [
        (0x1004, [25, 8, 12, 14, 30, 5, 1])
    ]


async def test_iv_curve_scan(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    events: list[WriteEvent] = []
    mock_modbus_unit.on_write(events.append)
    await hybrid.async_start_iv_curve_scan()
    assert [(e.address, e.values) for e in events] == [(0x1027, [1])]


# --- the BTS battery tower -------------------------------------------


async def test_battery_pack_is_selected_then_read(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    writes: list[WriteEvent] = []
    mock_modbus_unit.on_write(writes.append)
    pack = await hybrid.async_read_pack(string_nr=1, pack_nr=2)
    assert [(e.address, e.values) for e in writes] == [(0x9020, [(2 << 8) | 1])]
    assert pack.pack_model == "BTS5K"
    assert pack.string_count == 2
    assert pack.packs_per_string == 3
    assert pack.total_voltage == pytest.approx(51.2)
    assert pack.total_current == pytest.approx(-5.0)
    assert pack.soc == 88
    assert pack.pack_serial_number == "BTSPACK000000001"
    assert pack.cell_1_voltage == pytest.approx(3.3)
    assert pack.cell_16_voltage == pytest.approx(3.298)
    assert pack.pack_temperature_1 == pytest.approx(24.5)
    assert pack.pack_remaining_capacity == pytest.approx(100.0)
    assert pack.pack_time == datetime(2025, 8, 12, 14, 30, 5)


async def test_the_battery_tower_is_never_part_of_a_poll(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Packs share one register block, so a poll cannot read them all."""
    report = await hybrid.async_update()
    assert "battery_pack" not in report.updated
    assert not any(b.address >= 0x9000 for b in mock_modbus_unit.read_events)
