"""Settings and commands, the 0x1000 register block.

The device takes paired registers only as one block write.
"""

from __future__ import annotations

from modbus_connection.encode import encode_int
from modbus_connection.model import boolean, enum, flags, gauge, int32, integer

from ..model import SofarComponent
from ..variants import EPS, HYBRID, PM, PV, X3
from .enums import (
    BatConfigCellType,
    BatConfigProtocol,
    ChargerUseMode,
    EpsControlMode,
    FeedinLimitationMode,
    ParallelMasterslave,
    PassiveModeTimeoutAction,
    PowerControlFlags,
    RemoteSwitchOnOff,
    SyncRtcResult,
)


def _parallel_address(value: int) -> int:
    if not 0 <= value <= 10:
        raise ValueError(f"parallel address {value} is outside 0-10")
    return value


class RtcSyncResult(SofarComponent):
    """Result of the last real-time-clock write."""

    applies_to = HYBRID

    sync_rtc_result = enum(0x100A, SyncRtcResult, signed=False)
    """Update System Time Operation Result."""


class FeedInLimit(SofarComponent):
    """Feed-in (export) limitation settings."""

    applies_to = PV | HYBRID

    feedin_limitation_mode = enum(0x1023, FeedinLimitationMode, signed=False)
    feedin_max_power = gauge(0x1024, 100, signed=False, unit="W")
    """FeedIn: Maximum Power."""

    async def async_write_limit(
        self, mode: FeedinLimitationMode, max_power: int
    ) -> None:
        """Set the feed-in mode and its power ceiling, in watts.

        The device ignores either register written alone.
        """
        if max_power % 100:
            raise ValueError(f"feed-in power {max_power} is not a multiple of 100 W")
        await self._unit.write_registers(0x1023, [int(mode), max_power // 100])


class ActivePowerControl(SofarComponent):
    """Real-time cap on the inverter's own output, registers 1105/1106.

    Caps generation, not export; volatile, so safe to write often.
    """

    applies_to = PV | HYBRID

    power_control = flags(0x1105, PowerControlFlags, signed=False)
    """Which of 1106-1109 the device is currently acting on."""
    active_power_export_limit = gauge(0x1106, 0.1, signed=False, unit="%")
    """Output ceiling, as a percentage of rated power."""

    async def async_write_active_power_limit(
        self, enabled: bool, limit_pct: float
    ) -> None:
        """Cap the inverter's own output at ``limit_pct`` % of rated power.

        Disabling keeps 1106: the device ignores it while 1105 is unset.
        """
        if not 0 <= limit_pct <= 100:
            raise ValueError(f"active power limit {limit_pct}% is outside 0-100")
        control = PowerControlFlags.ACTIVE_POWER if enabled else PowerControlFlags(0)
        await self._unit.write_registers(0x1105, [int(control), round(limit_pct * 10)])


class EpsControl(SofarComponent):
    """Emergency-power-supply (off-grid) control settings."""

    applies_to = HYBRID | EPS

    eps_control = enum(0x1029, EpsControlMode, signed=False)
    """EPS Mode."""
    passive_eps_wait_time = integer(0x102A, signed=False, unit="s")
    """EPS Wait Time."""

    async def async_write_control(self, mode: EpsControlMode) -> None:
        """Set the EPS mode.

        The wait time is reserved, so it goes out as 0.
        """
        await self._unit.write_registers(0x1029, [int(mode), 0])


class BatteryActiveControl(SofarComponent):
    """Battery active-control switch."""

    applies_to = HYBRID

    battery_active_control = boolean(0x102B)
    """Battery Active Control (the plugin renders it Disabled/Enabled)."""


class ParallelControl(SofarComponent):
    """Parallel-system (multi-inverter) settings."""

    applies_to = X3 | PV | HYBRID | PM

    parallel_control = boolean(0x1035)
    """Parallel Control (the plugin renders it Disabled/Enabled)."""
    parallel_masterslave = enum(0x1036, ParallelMasterslave, signed=False)
    """Parallel Master-Salve."""
    parallel_address = integer(
        0x1037, signed=False, writable=_parallel_address, force_fc16=True
    )


class BatteryConfigId(SofarComponent):
    """Which battery the configuration block below describes."""

    applies_to = HYBRID
    register_ranges = ((0x1044, 0x1047),)

    bat_config_id = integer(0x1044, signed=False)
    bat_config_address_1 = integer(0x1045, signed=False)
    bat_config_protocol = enum(0x1046, BatConfigProtocol, signed=False)
    bat_config_overvoltage_protection = gauge(0x1047, 0.1, signed=False, unit="V")


class BatteryConfig(SofarComponent):
    """Charge and discharge limits of the selected battery."""

    applies_to = HYBRID
    register_ranges = ((0x1048, 0x105A),)

    bat_config_charging_voltage = gauge(0x1048, 0.1, signed=False, unit="V")
    bat_config_undervoltage_protection = gauge(0x1049, 0.1, signed=False, unit="V")
    bat_config_minimum_discharge_voltage = gauge(0x104A, 0.1, signed=False, unit="V")
    bat_config_maximum_charge_current_limit = gauge(
        0x104B, 0.01, signed=False, unit="A"
    )
    bat_config_maximum_discharge_current_limit = gauge(
        0x104C, 0.01, signed=False, unit="A"
    )
    bat_config_depth_of_discharge = integer(0x104D, signed=False, unit="%")
    bat_config_end_of_discharge = integer(0x104E, signed=False, unit="%")
    bat_config_capacity = integer(0x104F, signed=False, unit="Ah")
    bat_config_rated_battery_voltage = gauge(0x1050, 0.1, signed=False, unit="V")
    bat_config_cell_type = enum(0x1051, BatConfigCellType, signed=False)
    bat_config_eps_buffer = integer(0x1052, signed=False, unit="%")
    bat_config_address_2 = integer(0x1054, signed=False)
    bat_config_address_3 = integer(0x1055, signed=False)
    bat_config_address_4 = integer(0x1056, signed=False)
    bat_config_tempco = gauge(0x1057, 0.1, signed=True, unit="mV/Cell")
    """BatConfig: Lead Acid Battery Temperature Compensation Factor."""
    bat_config_rated_battery_voltage_2 = gauge(0x1058, 0.1, signed=False, unit="V")
    """BatConfig: Lead Acid Battery Recovery Buffer."""
    bat_config_voltage_float = gauge(0x105A, 0.1, signed=False, unit="V")
    """BatConfig: Lead Acid Battery Float Voltage."""


class RemoteControl(SofarComponent):
    """Remote on/off switch."""

    applies_to = PV | HYBRID

    remote_switch_on_off = enum(
        0x1104, RemoteSwitchOnOff, signed=False, writable=True, force_fc16=True
    )

    async def async_write_switch(self, state: RemoteSwitchOnOff) -> None:
        """Switch the inverter on or off."""
        await self.write("remote_switch_on_off", state)


class ChargerMode(SofarComponent):
    """The inverter's energy-management mode."""

    applies_to = HYBRID

    charger_use_mode = enum(
        0x1110, ChargerUseMode, signed=False, writable=True, force_fc16=True
    )

    async def async_write_mode(self, mode: ChargerUseMode) -> None:
        """Set the energy-management mode."""
        await self.write("charger_use_mode", mode)


class PassiveMode(SofarComponent):
    """Passive-mode setpoints: the inverter follows these power commands."""

    applies_to = HYBRID

    passive_mode_timeout = integer(0x1184, signed=False)
    """Passive: Timeout."""
    passive_mode_timeout_action = enum(0x1185, PassiveModeTimeoutAction, signed=False)
    """Passive: Timeout Action."""
    passive_mode_grid_power = int32(0x1187)
    """Passive: Desired Grid Power."""
    passive_mode_battery_power_min = int32(0x1189)
    """Passive: Minimum Battery Power."""
    passive_mode_battery_power_max = int32(0x118B)
    """Passive: Maximum Battery Power."""

    async def async_write_timeout(
        self, timeout: int, action: PassiveModeTimeoutAction
    ) -> None:
        """Set how long a passive-mode command holds, and what happens after."""
        await self._unit.write_registers(0x1184, [timeout, int(action)])

    async def async_write_power(
        self, grid_power: int, battery_min: int, battery_max: int
    ) -> None:
        """Command the passive-mode setpoints, in watts, in one write.

        The device takes the three int32 values only as one block.
        """
        words: list[int] = []
        for value in (grid_power, battery_min, battery_max):
            words += encode_int(value, count=2)
        await self._unit.write_registers(0x1187, words)
