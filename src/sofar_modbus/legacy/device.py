"""The top-level object for an older-generation Sofar inverter."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from modbus_connection import (
    IllegalDataAddressError,
    IllegalFunctionError,
    ModbusConnectionError,
    ModbusError,
    ModbusTimeoutError,
)
from modbus_connection.model import ComponentGroup

from ..model import SofarLegacyComponent, UpdateReport
from ..variants import EPS, HYBRID, PV, X1, X3, InverterType, matches
from .identity import LegacyIdentity
from .pv import HybridPvString1, HybridPvString2, PvCommon, SinglePhasePv, ThreePhasePv
from .storage import AcBatterySettings, Storage, StorageEps, StorageThreePhase

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

# Runs several components tile; reading a member apart wastes a request
# and isolates nothing. ``storage`` spans 0x0200-0x0245 (all S/T phase
# and EPS registers); ``pv_three_phase`` spans 0x0008-0x0020, covering
# ``pv_common``'s two temperatures. ``pv_single_phase`` stops short of
# those, so it stays its own failure domain. Pooled entries take their
# first member's poll-list slot, so a poll still walks front to back.
_POOLS: dict[str, tuple[str, ...]] = {
    "storage_block": ("storage", "storage_three_phase", "storage_eps"),
    "pv_block": ("pv_common", "pv_three_phase"),
}

# Serial-number prefix -> inverter bitmask, from the plugin's
# async_determineInverterType. This generation reports no model name.
_SERIAL_PREFIXES: tuple[tuple[str, InverterType], ...] = (
    ("SE1E", HYBRID | X1),
    ("SM1E", HYBRID | X1),
    ("ZE1E", HYBRID | X1),
    ("ZM1E", HYBRID | X1),
    ("SA1", PV | X1),
    ("SA3", PV | X1),
    ("SB1", PV | X1),
    ("ZA3", PV | X1),
    ("SC1", PV | X3),
    ("SD1", PV | X3),
    ("SF4", PV | X3),
    ("SH1", PV | X3),
    ("SJ2", PV | X3),
    ("SL1", PV | X3),
    ("SM1", PV),
)


def identify(serial: str) -> InverterType:
    """The inverter type a serial number implies, or ``InverterType(0)``."""
    for prefix, invertertype in _SERIAL_PREFIXES:
        if serial.startswith(prefix):
            return invertertype
    return InverterType(0)


class SofarLegacyInverter:
    """An older Sofar inverter reached through a ``ModbusUnit``.

    Read-only, RTU only -- no writable registers, no ASCII over TCP.
    """

    def __init__(
        self,
        unit: ModbusUnit,
        *,
        serial_number: str | None = None,
        inverter_type: InverterType | None = None,
    ) -> None:
        self._unit = unit
        self.serial_number = serial_number
        self.inverter_type = inverter_type

        self.identity = LegacyIdentity(unit)
        self.pv_common = PvCommon(unit)
        self.pv_single_phase = SinglePhasePv(unit)
        self.pv_three_phase = ThreePhasePv(unit)
        self.storage = Storage(unit)
        self.storage_three_phase = StorageThreePhase(unit)
        self.storage_eps = StorageEps(unit)
        self.hybrid_pv_1 = HybridPvString1(unit)
        self.hybrid_pv_2 = HybridPvString2(unit)
        self.battery_settings = AcBatterySettings(unit)

        # Built by setup from the members this inverter serves; see _POOLS.
        self.storage_block: ComponentGroup | None = None
        self.pv_block: ComponentGroup | None = None

        self._polled: list[str] | None = None

    @property
    def pv_power_total(self) -> float | None:
        """Total PV power of a hybrid inverter, summed over its two strings."""
        powers = [self.hybrid_pv_1.pv_power_1, self.hybrid_pv_2.pv_power_2]
        present = [p for p in powers if p is not None]
        return sum(present) if present else None

    async def _async_setup(self) -> None:
        """Read the serial number, settle the model, and pick what to poll."""
        if self.serial_number is None:
            await self.identity.async_update(notify=False)
            raw = self.identity.serial_number
            assert raw is not None
            # The plugin strips the punctuation these boards pad the field with.
            self.serial_number = re.sub(r"[^A-Za-z0-9 -]", "", raw)
        if self.inverter_type is None:
            self.inverter_type = identify(self.serial_number)
        inverter_type = self.inverter_type
        assert inverter_type is not None
        if (
            EPS not in inverter_type
            and matches(inverter_type, self.storage_eps.applies_to & ~EPS)
            and await self._async_probe_eps()
        ):
            inverter_type |= EPS
            self.inverter_type = inverter_type
        served = [
            name
            for name in (
                "pv_common",
                "pv_single_phase",
                "pv_three_phase",
                "storage",
                "storage_three_phase",
                "storage_eps",
                "hybrid_pv_1",
                "hybrid_pv_2",
                "battery_settings",
            )
            if matches(inverter_type, getattr(self, name).applies_to)
        ]
        self._polled = self._pool(served)

    async def _async_probe_eps(self) -> bool:
        """Whether this inverter answers the EPS registers."""
        try:
            await self.storage_eps.async_update(notify=False)
        except (IllegalDataAddressError, IllegalFunctionError):
            return False
        return True

    def _pool(self, served: list[str]) -> list[str]:
        """The poll list, with each served run of _POOLS replaced by its group."""
        stands_for: dict[str, str] = {}
        for pool, members in _POOLS.items():
            present = [name for name in members if name in served]
            if len(present) < 2:
                continue  # nothing to pool; the lone member polls as itself
            setattr(
                self,
                pool,
                ComponentGroup(self._unit, [getattr(self, n) for n in present]),
            )
            stands_for |= dict.fromkeys(present, pool)

        polled: list[str] = []
        for name in served:
            entry = stands_for.get(name, name)
            if entry not in polled:
                polled.append(entry)
        return polled

    async def async_update(self) -> UpdateReport:
        """Refresh every sub-system this inverter serves, one at a time.

        Same contract as ``SofarInverter``: a dead link raises.
        """
        if self._polled is None:
            await self._async_setup()
            assert self._polled is not None
        updated: set[str] = set()
        failed: dict[str, ModbusError] = {}
        for name in self._polled:
            target: SofarLegacyComponent | ComponentGroup = getattr(self, name)
            try:
                await target.async_update(notify=False)
            except ModbusConnectionError:
                raise
            except ModbusTimeoutError as err:
                if not updated and not failed:
                    raise  # nothing answered at all: assume the rest time out too
                failed[name] = err
            except ModbusError as err:
                failed[name] = err
            else:
                updated.add(name)
        for name in self._polled:
            if name in updated:
                fresh: SofarLegacyComponent | ComponentGroup = getattr(self, name)
                fresh.notify()
        return UpdateReport(updated, failed)

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Every register this inverter reads, undecoded, for diagnostics.

        Nothing notifies here: a diagnostics download is not a poll.
        """
        if self._polled is None:
            await self._async_setup()
            assert self._polled is not None
        raw: dict[str, dict[int, int | bool]] = {}
        for name in ("identity", *self._polled):
            target: SofarLegacyComponent | ComponentGroup = getattr(self, name)
            for space, values in (await target.async_read_raw(notify=False)).items():
                raw.setdefault(space, {}).update(values)
        return raw
