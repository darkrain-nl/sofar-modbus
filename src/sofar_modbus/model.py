"""The component bases the two protocol generations build on."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from modbus_connection import ModbusError
from modbus_connection.model import Component

from .variants import InverterType


class SofarComponentBase(Component):
    """Tags a sub-system with the inverter mask deciding if it's polled."""

    applies_to: InverterType = InverterType(0)


class SofarComponent(SofarComponentBase):
    """A sub-system of the current-generation (HYD / KTL-X) register map."""

    max_span = 48  # the plugin's block_size for this generation


class SofarLegacyComponent(SofarComponentBase):
    """A sub-system of the older register map."""

    max_span = 100  # the plugin's block_size for this generation


class TornReadCorrectedComponent(SofarComponent):
    """A component whose TOTAL_INCREASING fields survive a torn read intact."""

    # Fraction below the high-water mark still counted as a torn read.
    _dip_tolerance: ClassVar[float] = 0.01
    _total_increasing_fields: ClassVar[tuple[str, ...]] = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the component and its high-water tracking."""
        super().__init__(*args, **kwargs)
        self._high_water: dict[str, float] = {}
        self._corrected: dict[str, float] = {}
        self.add_update_listener(self._correct_totals)

    def corrected(self, name: str) -> float | None:
        """The torn-read-corrected value of a declared total field."""
        return self._corrected.get(name)

    def seed_high_water(self, name: str, value: float) -> None:
        """Prime a field's high-water mark, e.g. from a restored HA state."""
        self._high_water[name] = value

    def _correct_totals(self) -> None:
        """Hold each total at its high-water mark through a torn read."""
        for name in self._total_increasing_fields:
            raw = self._values.get(name)
            if not isinstance(raw, (int, float)):
                continue
            high_water = self._high_water.get(name)
            if (
                high_water is None
                or raw >= high_water
                or raw < high_water * (1 - self._dip_tolerance)
            ):
                self._high_water[name] = raw
                self._corrected[name] = raw
            else:
                self._corrected[name] = high_water


@dataclass(frozen=True)
class UpdateReport:
    """What one poll refreshed; a failed component keeps its prior values."""

    updated: set[str]
    failed: dict[str, ModbusError]

    @property
    def complete(self) -> bool:
        """Whether every polled component refreshed."""
        return not self.failed
