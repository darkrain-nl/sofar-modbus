"""The top-level object for an older-generation Sofar inverter."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Self

from modbus_connection.model import ComponentGroup, Device, Raw

from ..model import REFUSALS, SofarLegacyComponent, UpdateReport
from ..variants import EPS, HYBRID, PV, X1, X3, InverterType, matches
from .identity import LegacyIdentity
from .pv import HybridPvString1, HybridPvString2, PvCommon, SinglePhasePv, ThreePhasePv
from .storage import AcBatterySettings, Storage, StorageEps, StorageThreePhase

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

_LOGGER = logging.getLogger(__name__)

# Members of one tiled run; reading one apart wastes a request.
# ``storage`` spans 0x0200-0x0245, every S/T phase and EPS register.
_STORAGE_BLOCK = ("storage", "storage_three_phase", "storage_eps")
# ``pv_three_phase`` spans 0x0008-0x0020, over ``pv_common``'s two
# temperatures; ``pv_single_phase`` stops short, so it stays apart.
_PV_BLOCK = ("pv_common", "pv_three_phase")

# Kept in step with the plugin's async_determineInverterType. This
# generation reports no model name.
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


class SofarLegacyInverter(Device):
    """An older Sofar inverter reached through a ``ModbusUnit``.

    Read-only and RTU only: no writable registers, no ASCII over TCP.
    """

    def __init__(
        self,
        unit: ModbusUnit,
        *,
        serial_number: str,
        inverter_type: InverterType | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(unit)
        unit.require_timeout(timeout)
        detected = identify(serial_number)
        if inverter_type is None and detected:
            _LOGGER.debug("Serial %s identifies as %s", serial_number, detected.name)
        elif inverter_type is None:
            _LOGGER.debug("Serial %s matches no known model", serial_number)
        self.serial_number = serial_number
        self.inverter_type = detected if inverter_type is None else inverter_type

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
        self._members: dict[str, SofarLegacyComponent] = {
            "pv_common": self.pv_common,
            "pv_single_phase": self.pv_single_phase,
            "pv_three_phase": self.pv_three_phase,
            "storage": self.storage,
            "storage_three_phase": self.storage_three_phase,
            "storage_eps": self.storage_eps,
            "hybrid_pv_1": self.hybrid_pv_1,
            "hybrid_pv_2": self.hybrid_pv_2,
            "battery_settings": self.battery_settings,
        }

        # Built by setup from the members this inverter serves.
        self.storage_block: ComponentGroup | None = None
        self.pv_block: ComponentGroup | None = None

        self._polled: list[str] = []

    @classmethod
    async def async_detect(
        cls, unit: ModbusUnit, *, timeout: float | None = None
    ) -> Self:
        """Build an inverter for a caller that does not know its serial."""
        unit.require_timeout(timeout)
        identity = LegacyIdentity(unit)
        await identity.async_update(notify=False)
        raw = identity.serial_number
        assert raw is not None
        # These boards pad the field with punctuation.
        device = cls(
            unit, serial_number=re.sub(r"[^A-Za-z0-9 -]", "", raw), timeout=timeout
        )
        device.identity = identity
        return device

    @property
    def pv_power_total(self) -> float | None:
        """Total PV power of a hybrid inverter, summed over its two strings."""
        present = [
            power
            for power in (self.hybrid_pv_1.pv_power_1, self.hybrid_pv_2.pv_power_2)
            if power is not None
        ]
        return sum(present) if present else None

    async def _async_setup(self) -> None:
        """Settle which optional sub-systems this inverter serves."""
        if (
            EPS not in self.inverter_type
            and matches(self.inverter_type, self.storage_eps.applies_to & ~EPS)
            and await self._async_probe_eps()
        ):
            self.inverter_type |= EPS
        served = [
            name
            for name, component in self._members.items()
            if matches(self.inverter_type, component.applies_to)
        ]
        self.storage_block = self._group(served, _STORAGE_BLOCK)
        self.pv_block = self._group(served, _PV_BLOCK)
        # A pooled run takes its first member's slot in the poll order.
        stands_for: dict[str, str] = {}
        if self.storage_block is not None:
            stands_for |= dict.fromkeys(_STORAGE_BLOCK, "storage_block")
        if self.pv_block is not None:
            stands_for |= dict.fromkeys(_PV_BLOCK, "pv_block")
        self._polled = list(
            dict.fromkeys(stands_for.get(name, name) for name in served)
        )
        _LOGGER.debug(
            "Inverter %s is %s; polling: %s",
            self.serial_number,
            self.inverter_type.name or "an unknown type",
            ", ".join(self._polled) or "nothing",
        )

    async def _async_probe_eps(self) -> bool:
        """Whether this inverter answers the EPS registers."""
        try:
            await self.storage_eps.async_update(notify=False)
        except REFUSALS as err:
            _LOGGER.debug(
                "Inverter %s refuses the EPS registers: %s", self.serial_number, err
            )
            return False
        _LOGGER.debug("Inverter %s answers the EPS registers", self.serial_number)
        return True

    def _group(
        self, served: list[str], members: tuple[str, ...]
    ) -> ComponentGroup | None:
        """The served ``members`` as one group; ``None`` below two."""
        present = [self._members[name] for name in members if name in served]
        if len(present) < 2:
            return None
        return ComponentGroup(self.modbus_unit, present)

    async def async_update(self) -> UpdateReport:
        """Refresh every sub-system this inverter serves, one at a time.

        Same contract as ``SofarInverter``: a dead link raises.
        """
        await self.async_ensure_setup()
        return await self.async_poll(self._polled)

    async def async_read_raw(self, names: Iterable[str] | None = None) -> Raw:
        """Every register this inverter reads, undecoded, for diagnostics.

        Nothing notifies here: a diagnostics download is not a poll.
        """
        await self.async_ensure_setup()
        if names is None:
            names = ("identity", *self._polled)
        return await super().async_read_raw(names)
