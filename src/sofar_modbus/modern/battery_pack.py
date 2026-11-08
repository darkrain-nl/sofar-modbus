"""Support for BTS battery towers and their packs."""

from __future__ import annotations

from asyncio import sleep
from datetime import datetime
from typing import TYPE_CHECKING

from modbus_connection.model import bits, gauge, integer, string, uint32

from ..model import SofarComponent
from ..variants import BAT_BTS

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

_BMS_INQUIRE_REGISTER = 0x9020  # selects which pack 0x9044+ reports
_PACK_ID_REGISTER = 0x9044  # which pack it reports right now

# The tower switches packs a moment after the write, not with it.
_SETTLE_STEP = 0.3  # seconds between pack_id checks
_SETTLE_STEPS = 10  # checks before reading whatever it serves


class BatteryTower(SofarComponent):
    """Describe a BTS battery tower's layout."""

    applies_to = BAT_BTS
    register_ranges = ((0x9007, 0x900D),)

    model = string(0x9007, 4)
    bms_version = integer(0x900B, signed=False)
    parallel_group_count = bits(0x900D, 8, 8)
    """Battery groups running in parallel (high byte of 0x900D)."""
    packs_per_group = bits(0x900D, 0, 8)
    """Packs in each group (low byte of 0x900D)."""


class BatteryPack(SofarComponent):
    """One BTS battery pack, as selected through the BMS inquiry register."""

    applies_to = BAT_BTS
    register_ranges = (
        (0x9007, 0x900A),
        (0x900B, 0x9013),
        (0x9044, 0x9046),
        (0x9048, 0x907C),
    )

    pack_model = string(0x9007, 4)
    bms_version = integer(0x900B, signed=False)
    packs_per_group = bits(0x900D, 0, 8)
    """Packs in each group (low byte of 0x900D)."""
    parallel_group_count = bits(0x900D, 8, 8)
    """Battery groups running in parallel (high byte of 0x900D)."""
    realtime_capacity = integer(0x900E, signed=False, unit="%")
    total_voltage = gauge(0x900F, 0.1, signed=False, unit="V")
    total_current = gauge(0x9010, 0.1, signed=True, unit="A")
    soc = integer(0x9012, signed=False, unit="%")
    soh = integer(0x9013, signed=False, unit="%")
    pack_id = integer(0x9044, signed=False)
    """Which pack the block currently reports: group<<8 | pack."""
    _pack_time_raw = uint32(0x9045)
    pack_serial_number = string(0x9048, 9)
    cell_1_voltage = gauge(0x9051, 0.001, signed=False, unit="V")
    cell_2_voltage = gauge(0x9052, 0.001, signed=False, unit="V")
    cell_3_voltage = gauge(0x9053, 0.001, signed=False, unit="V")
    cell_4_voltage = gauge(0x9054, 0.001, signed=False, unit="V")
    cell_5_voltage = gauge(0x9055, 0.001, signed=False, unit="V")
    cell_6_voltage = gauge(0x9056, 0.001, signed=False, unit="V")
    cell_7_voltage = gauge(0x9057, 0.001, signed=False, unit="V")
    cell_8_voltage = gauge(0x9058, 0.001, signed=False, unit="V")
    cell_9_voltage = gauge(0x9059, 0.001, signed=False, unit="V")
    cell_10_voltage = gauge(0x905A, 0.001, signed=False, unit="V")
    cell_11_voltage = gauge(0x905B, 0.001, signed=False, unit="V")
    cell_12_voltage = gauge(0x905C, 0.001, signed=False, unit="V")
    cell_13_voltage = gauge(0x905D, 0.001, signed=False, unit="V")
    cell_14_voltage = gauge(0x905E, 0.001, signed=False, unit="V")
    cell_15_voltage = gauge(0x905F, 0.001, signed=False, unit="V")
    cell_16_voltage = gauge(0x9060, 0.001, signed=False, unit="V")
    cell_17_voltage = gauge(0x9061, 0.001, signed=False, unit="V")
    cell_18_voltage = gauge(0x9062, 0.001, signed=False, unit="V")
    cell_19_voltage = gauge(0x9063, 0.001, signed=False, unit="V")
    cell_20_voltage = gauge(0x9064, 0.001, signed=False, unit="V")
    cell_21_voltage = gauge(0x9065, 0.001, signed=False, unit="V")
    cell_22_voltage = gauge(0x9066, 0.001, signed=False, unit="V")
    cell_23_voltage = gauge(0x9067, 0.001, signed=False, unit="V")
    cell_24_voltage = gauge(0x9068, 0.001, signed=False, unit="V")
    cell_max_voltage = gauge(0x9069, 0.001, signed=False, unit="V")
    cell_min_voltage = gauge(0x906A, 0.001, signed=False, unit="V")
    pack_temperature_1 = gauge(0x906B, 0.1, signed=True, unit="°C")
    pack_temperature_2 = gauge(0x906C, 0.1, signed=True, unit="°C")
    pack_temperature_3 = gauge(0x906D, 0.1, signed=True, unit="°C")
    pack_temperature_4 = gauge(0x906E, 0.1, signed=True, unit="°C")
    pack_temperature_mos = gauge(0x906F, 0.1, signed=True, unit="°C")
    pack_temperature_env = gauge(0x9070, 0.1, signed=True, unit="°C")
    pack_current = gauge(0x9071, 0.1, signed=True, unit="A")
    pack_remaining_capacity = gauge(0x9072, 0.1, signed=False, unit="Ah")
    pack_full_charge_capacity = gauge(0x9073, 0.1, signed=False, unit="Ah")
    pack_cycles = integer(0x9074, signed=False)
    cell_balancing = integer(0x9075, signed=False)
    """Which cells are balancing: bit 0 is cell 1, bit 15 cell 16."""
    # The vendor publishes no bit meanings for these three status words.
    pack_alarm_state = integer(0x9076, signed=False)
    pack_protect_state = integer(0x9077, signed=False)
    pack_fault_state = integer(0x9078, signed=False)
    pack_total_voltage = gauge(0x9079, 0.1, signed=False, unit="V")
    pack_soc = integer(0x907A, signed=False, unit="%")
    packs_in_group = integer(0x907B, signed=False)
    """How many packs this pack's group holds."""
    cells_in_pack = integer(0x907C, signed=False)
    """How many cells this pack has in series."""

    def __init__(
        self, unit: ModbusUnit, *, group_nr: int = 0, pack_nr: int = 0
    ) -> None:
        """Initialize the pack."""
        super().__init__(unit)
        self.group_nr = group_nr
        self.pack_nr = pack_nr
        self.answered = False
        """Whether the last read succeeded and served this pack."""

    @property
    def cell_voltages(self) -> tuple[float | None, ...]:
        """Cell voltages in order; index 0 is cell 1."""
        return (
            self.cell_1_voltage,
            self.cell_2_voltage,
            self.cell_3_voltage,
            self.cell_4_voltage,
            self.cell_5_voltage,
            self.cell_6_voltage,
            self.cell_7_voltage,
            self.cell_8_voltage,
            self.cell_9_voltage,
            self.cell_10_voltage,
            self.cell_11_voltage,
            self.cell_12_voltage,
            self.cell_13_voltage,
            self.cell_14_voltage,
            self.cell_15_voltage,
            self.cell_16_voltage,
            self.cell_17_voltage,
            self.cell_18_voltage,
            self.cell_19_voltage,
            self.cell_20_voltage,
            self.cell_21_voltage,
            self.cell_22_voltage,
            self.cell_23_voltage,
            self.cell_24_voltage,
        )

    @property
    def cell_temperatures(self) -> tuple[float | None, ...]:
        """Cell temperature sensors 1 to 4 in order."""
        return (
            self.pack_temperature_1,
            self.pack_temperature_2,
            self.pack_temperature_3,
            self.pack_temperature_4,
        )

    @property
    def pack_time(self) -> datetime | None:
        """The pack's clock, from the bit-packed timestamp at 0x9045."""
        raw = self._pack_time_raw
        if raw is None:
            return None
        fields = []
        for width in (6, 6, 5, 5, 4, 6):  # second, minute, hour, day, month, year
            fields.append(raw & ((1 << width) - 1))
            raw >>= width
        second, minute, hour, day, month, year = fields
        try:
            return datetime(2000 + year, month, day, hour, minute, second)
        except ValueError:  # an unset clock reports out-of-range parts
            return None

    async def async_select(self, pack_nr: int, group_nr: int = 0) -> None:
        """Point the block at one pack and wait for the tower to switch."""
        for name, value in (("pack", pack_nr), ("group", group_nr)):
            if not 0 <= value <= 15:
                raise ValueError(f"battery {name} {value} is outside 0-15")
        selection = group_nr << 8 | pack_nr
        # Some towers reject the write yet already serve the wanted pack.
        if await self._async_serves(selection):
            return
        await self._unit.write_register(_BMS_INQUIRE_REGISTER, selection)
        if await self._async_serves(selection):
            return
        for _ in range(_SETTLE_STEPS):
            await sleep(_SETTLE_STEP)
            if await self._async_serves(selection):
                return

    async def _async_serves(self, selection: int) -> bool:
        """Whether the block reports the pack ``selection`` names."""
        return (await self._unit.read_holding_registers(_PACK_ID_REGISTER, 1))[
            0
        ] & 0x0FFF == selection
