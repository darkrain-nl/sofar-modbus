"""The inverter's historical event log, the 0x1480 register block."""

from __future__ import annotations

from datetime import datetime

from modbus_connection.model import raw_register, repeating_group

from ..model import SofarComponent
from ..variants import HYBRID, PV
from .faults import FAULTS_BY_ID, FaultLogEntry

# The most entries the spec allows in one read.
_ENTRIES_READ = 10


class FaultLogSlot(SofarComponent):
    """One four-register entry of the event log."""

    fault_id = raw_register(0x1480)
    _year_month = raw_register(0x1481)
    _day_hour = raw_register(0x1482)
    _minute_second = raw_register(0x1483)

    @property
    def empty(self) -> bool:
        """Whether the slot holds no entry yet."""
        return not any(
            (self.fault_id, self._year_month, self._day_hour, self._minute_second)
        )

    @property
    def occurred_at(self) -> datetime | None:
        """When the entry was logged; ``None`` if the parts are no date."""
        year_month = self._year_month
        day_hour = self._day_hour
        minute_second = self._minute_second
        if year_month is None or day_hour is None or minute_second is None:
            return None
        try:
            return datetime(
                2000 + (year_month >> 8),
                year_month & 0xFF,
                day_hour >> 8,
                day_hour & 0xFF,
                minute_second >> 8,
                minute_second & 0xFF,
            )
        except ValueError:
            return None

    @property
    def entry(self) -> FaultLogEntry | None:
        """The logged fault; ``None`` for an unknown id or a bad date."""
        if self.fault_id is None or (fault := FAULTS_BY_ID.get(self.fault_id)) is None:
            return None
        if (occurred_at := self.occurred_at) is None:
            return None
        return FaultLogEntry(fault, occurred_at)


class FaultLog(SofarComponent):
    """The newest entries of the inverter's historical event log."""

    applies_to = PV | HYBRID

    slots = repeating_group(_ENTRIES_READ, FaultLogSlot, stride=4)

    @property
    def entries(self) -> tuple[FaultLogEntry, ...]:
        """Valid entries, newest first; empty before the first read."""
        return tuple(entry for slot in self.slots if (entry := slot.entry) is not None)

    @property
    def well_formed(self) -> bool:
        """Whether every slot reads as empty or as a dated entry.

        A model without the log answers the block with junk instead.
        """
        return all(slot.empty or slot.occurred_at is not None for slot in self.slots)
