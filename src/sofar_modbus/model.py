"""The component bases the two protocol generations build on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Self, overload

from modbus_connection.model import Component, RegisterField, UpdateReport

from .variants import InverterType

__all__ = [
    "CorrectedTotal",
    "SofarComponent",
    "SofarComponentBase",
    "SofarLegacyComponent",
    "TornReadCorrectedComponent",
    "UpdateReport",
    "corrected_total",
]


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

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Collect the fields a ``corrected_total`` declares."""
        super().__init_subclass__(**kwargs)
        cls._total_increasing_fields = tuple(
            dict.fromkeys(
                value.field.name
                for klass in reversed(cls.__mro__)
                for value in vars(klass).values()
                if isinstance(value, _CorrectedTotalField)
            )
        )

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


class CorrectedTotal:
    """One torn-read-corrected total, read and seeded by the same handle."""

    def __init__(self, component: TornReadCorrectedComponent, name: str) -> None:
        """Initialize the handle."""
        self.component = component
        self.name = name

    @property
    def value(self) -> float | None:
        """The corrected value; ``None`` until the first poll."""
        return self.component.corrected(self.name)

    def seed(self, value: float) -> None:
        """Prime the high-water mark, e.g. from a restored HA state."""
        self.component.seed_high_water(self.name, value)


class _CorrectedTotalField:
    """Declare a total field and hand out its ``CorrectedTotal``."""

    def __init__(self, field: RegisterField[float]) -> None:
        """Initialize the declaration."""
        self.field = field

    if TYPE_CHECKING:

        @overload
        def __get__(self, obj: None, objtype: Any = ...) -> Self: ...

        @overload
        def __get__(
            self, obj: TornReadCorrectedComponent, objtype: Any = ...
        ) -> CorrectedTotal: ...

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        """The handle on an instance; the declaration on the class."""
        if obj is None:
            return self
        return CorrectedTotal(obj, self.field.name)


def corrected_total(field: RegisterField[float]) -> _CorrectedTotalField:
    """Declare ``field`` a TOTAL_INCREASING total to correct."""
    return _CorrectedTotalField(field)
