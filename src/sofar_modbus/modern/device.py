"""The top-level object for a current-generation Sofar inverter."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from modbus_connection import (
    IllegalDataAddressError,
    IllegalFunctionError,
    ModbusConnectionError,
    ModbusError,
    ModbusTimeoutError,
)
from modbus_connection.decode import decode_string

from ..model import SofarComponent, UpdateReport
from ..variants import (
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
    matches,
)
from .battery import BatteryStrings1To2, BatteryStrings3To8, BatteryTotals
from .battery_pack import BatteryPack
from .energy import BatteryEnergy, EnergyTotals
from .inverter import GridOutput, Identity, InverterState
from .offgrid import OffGridSinglePhase, OffGridThreePhase, OffGridTotals
from .pv import (
    PvString3,
    PvString4,
    PvStrings1To2,
    PvStrings5To6,
    PvStrings7To8,
    PvStrings9To10,
)
from .settings import (
    ActivePowerControl,
    BatteryActiveControl,
    BatteryConfig,
    BatteryConfigId,
    ChargerMode,
    EpsControl,
    FeedInLimit,
    ParallelControl,
    PassiveMode,
    RemoteControl,
    RtcSyncResult,
)

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

SERIAL_REGISTER = 0x0445
SERIAL_WORDS = 7

_SET_TIME_REGISTER = 0x1004
_IV_CURVE_SCAN_REGISTER = 0x1027

# Ported from the plugin's async_determineInverterType; ordered
# longest-prefix-first so the first match is the most specific one.
_SERIAL_PREFIXES: tuple[tuple[str, InverterType, str | None], ...] = (
    ("SP1ES120N6", HYBRID | X3, "HYD20KTL-3P"),
    ("SQ1ES1", PV | X3 | GEN | MPPT10, "100kW KTLX-G4"),
    ("SP1", HYBRID | X3 | GEN | BAT_BTS, "HYDxxKTL-3P"),
    ("SP2", HYBRID | X3 | GEN | BAT_BTS, "HYDxxKTL-3P 2nd"),
    ("ZP1", HYBRID | X3 | GEN, "HYDxx ZSS"),
    ("ZP2", HYBRID | X3 | GEN, "HYDxx ZSS"),
    ("SM2E", HYBRID | X1 | GEN, "HYDxxxxES"),
    ("ZM2E", HYBRID | X1 | GEN, "HYDxxxxKTL ZCS HP"),
    ("SH3E", PV | X1 | GEN, "4.6 KTLM-G3"),
    ("SS2E", PV | X3 | GEN, "4.4 KTLX-G3"),
    ("ZS2E", PV | X3 | GEN, "12 Azzurro KTL-V3"),
    ("SA1", PV | X1, None),
    ("SB1", PV | X1, None),
    ("SC1", PV | X3, None),
    ("SD1", PV | X3, None),
    ("SF4", PV | X3, None),
    ("SH1", HYBRID | X3 | GEN | BAT_BTS, "HYD5...8KTL-3P"),
    ("SL1", PV | X3, None),
    ("SJ2", PV | X3, None),
    ("SS1", PV | X3 | GEN, None),
)


def identify(serial: str) -> tuple[InverterType, str | None]:
    """The inverter type and model a serial number implies.

    Unrecognised serials return ``InverterType(0)``; pass it explicitly.
    """
    for prefix, invertertype, model in _SERIAL_PREFIXES:
        if serial.startswith(prefix):
            return invertertype, model
    return InverterType(0), None


class SofarInverter:
    """A current-generation Sofar inverter reached through a ``ModbusUnit``.

    Build the unit from RTU -- ASCII framing over TCP is unsupported.
    """

    def __init__(
        self,
        unit: ModbusUnit,
        *,
        serial_number: str | None = None,
        model: str | None = None,
        inverter_type: InverterType | None = None,
        read_pm: bool = False,
    ) -> None:
        """Set up the sub-systems.

        ``read_pm`` reads parallel-system registers an inverter refuses.
        """
        self._unit = unit
        self._options = PM if read_pm else InverterType(0)
        self.model = model
        self.serial_number = serial_number
        self.inverter_type = (
            inverter_type | self._options if inverter_type is not None else None
        )

        self.state = InverterState(unit)
        self.identity = Identity(unit)
        self.grid = GridOutput(unit)
        self.offgrid = OffGridTotals(unit)
        self.offgrid_single_phase = OffGridSinglePhase(unit)
        self.offgrid_three_phase = OffGridThreePhase(unit)
        self.pv_1_2 = PvStrings1To2(unit)
        self.pv_3 = PvString3(unit)
        self.pv_4 = PvString4(unit)
        self.pv_5_6 = PvStrings5To6(unit)
        self.pv_7_8 = PvStrings7To8(unit)
        self.pv_9_10 = PvStrings9To10(unit)
        self.battery_1_2 = BatteryStrings1To2(unit)
        self.battery_3_8 = BatteryStrings3To8(unit)
        self.battery_totals = BatteryTotals(unit)
        self.energy = EnergyTotals(unit)
        self.battery_energy = BatteryEnergy(unit)
        self.rtc_sync = RtcSyncResult(unit)
        self.feed_in = FeedInLimit(unit)
        self.eps = EpsControl(unit)
        self.battery_active_control = BatteryActiveControl(unit)
        self.parallel = ParallelControl(unit)
        self.battery_config_id = BatteryConfigId(unit)
        self.battery_config = BatteryConfig(unit)
        self.remote = RemoteControl(unit)
        self.active_power_control = ActivePowerControl(unit)
        self.charger = ChargerMode(unit)
        self.passive = PassiveMode(unit)
        # Read via async_read_pack(), one pack at a time; never in the poll.
        self.battery_pack = BatteryPack(unit)

        self._readings: list[str] | None = None
        self._settings: list[str] | None = None

    @property
    def has_battery_tower(self) -> bool:
        """Whether this inverter reports a BTS battery tower."""
        return self.inverter_type is not None and BAT_BTS in self.inverter_type

    async def _async_setup(self) -> None:
        """Read the serial number, settle the model, and pick what to poll."""
        if self.serial_number is None:
            words = await self._unit.read_holding_registers(
                SERIAL_REGISTER, SERIAL_WORDS
            )
            self.serial_number = decode_string(words)
        if self.inverter_type is None:
            detected, model = identify(self.serial_number)
            self.inverter_type = detected | self._options
            if self.model is None:
                self.model = model
        elif self.model is None:
            _, model = identify(self.serial_number)
            if model is not None:
                self.model = model
        inverter_type = self.inverter_type
        assert inverter_type is not None
        if (
            EPS not in inverter_type
            and matches(inverter_type, self.offgrid.applies_to & ~EPS)
            and await self._async_probe_eps()
        ):
            inverter_type |= EPS
            self.inverter_type = inverter_type
        self._readings = [
            name
            for name in (
                "state",
                "grid",
                "offgrid",
                "offgrid_single_phase",
                "offgrid_three_phase",
                "pv_1_2",
                "pv_3",
                "pv_4",
                "pv_5_6",
                "pv_7_8",
                "pv_9_10",
                "battery_1_2",
                "battery_3_8",
                "battery_totals",
                "energy",
                "battery_energy",
            )
            if matches(inverter_type, getattr(self, name).applies_to)
        ]
        self._settings = [
            name
            for name in (
                "identity",
                "rtc_sync",
                "feed_in",
                "eps",
                "battery_active_control",
                "parallel",
                "battery_config_id",
                "battery_config",
                "remote",
                "active_power_control",
                "charger",
                "passive",
            )
            if matches(inverter_type, getattr(self, name).applies_to)
        ]

    async def _async_probe_eps(self) -> bool:
        """Whether this inverter answers the off-grid (EPS) block."""
        try:
            await self.offgrid.async_update(notify=False)
        except (IllegalDataAddressError, IllegalFunctionError):
            return False
        return True

    def _notify(self, report: UpdateReport) -> None:
        """Fire listeners on every component that successfully refreshed."""
        for name in report.updated:
            fresh: SofarComponent = getattr(self, name)
            fresh.notify()

    async def async_update_readings(self) -> UpdateReport:
        """Refresh telemetry measurements (power, energy, battery, state)."""
        if self._readings is None:
            await self._async_setup()
            assert self._readings is not None
        report = await self._async_poll(self._readings)
        self._notify(report)
        return report

    async def async_update_settings(self) -> UpdateReport:
        """Refresh configuration registers (charger mode, limits, battery config).

        Split from telemetry: configuration only changes when written.
        """
        if self._settings is None:
            await self._async_setup()
            assert self._settings is not None
        report = await self._async_poll(self._settings)
        self._notify(report)
        return report

    async def async_update(self) -> UpdateReport:
        """Refresh readings and settings together in one report."""
        if self._readings is None or self._settings is None:
            await self._async_setup()
            assert self._readings is not None and self._settings is not None
        report = await self._async_poll(self._readings)
        await self._async_poll(self._settings, report)
        self._notify(report)
        return report

    async def _async_poll(
        self,
        targets: Sequence[str],
        report: UpdateReport | None = None,
    ) -> UpdateReport:
        """Read each component on its own, adding what happened to ``report``.

        A dead link raises instead of reporting a per-component failure.
        """
        if report is None:
            report = UpdateReport(set(), {})
        for name in targets:
            component: SofarComponent = getattr(self, name)
            try:
                await component.async_update(notify=False)
            except ModbusConnectionError:
                raise
            except ModbusTimeoutError as err:
                if not report.updated and not report.failed:
                    raise  # nothing answered at all: assume the rest time out too
                report.failed[name] = err
            except ModbusError as err:
                report.failed[name] = err
            else:
                report.updated.add(name)
        return report

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Every register this inverter reads, undecoded — for diagnostics.

        ``battery_pack`` is excluded: no way to say which pack it is.
        """
        if self._readings is None or self._settings is None:
            await self._async_setup()
            assert self._readings is not None and self._settings is not None
        raw: dict[str, dict[int, int | bool]] = {}
        for name in (*self._readings, *self._settings):
            component: SofarComponent = getattr(self, name)
            for space, values in (await component.async_read_raw(notify=False)).items():
                raw.setdefault(space, {}).update(values)
        return raw

    async def async_read_pack(self, string_nr: int, pack_nr: int) -> BatteryPack:
        """Select a BTS pack and read it.

        Check ``pack_id``: a not-yet-switched tower still answers.
        """
        await self.battery_pack.async_select(string_nr, pack_nr)
        await self.battery_pack.async_update()
        return self.battery_pack

    async def async_set_time(self, when: datetime | None = None) -> None:
        """Write the inverter's clock.

        ``rtc_sync`` reports whether the seven-register write took.
        """
        moment = when or datetime.now()
        await self._unit.write_registers(
            _SET_TIME_REGISTER,
            [
                moment.year % 100,
                moment.month,
                moment.day,
                moment.hour,
                moment.minute,
                moment.second,
                1,
            ],
        )

    async def async_start_iv_curve_scan(self) -> None:
        """Ask the inverter to sweep its PV strings' I-V curves."""
        await self._unit.write_register(_IV_CURVE_SCAN_REGISTER, 1)
