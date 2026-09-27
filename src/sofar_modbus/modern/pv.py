"""PV strings, the 0x0580 register block, one component per MPPT tier."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from modbus_connection.model import RegisterField, gauge

from ..model import SofarComponent
from ..variants import GEN, HYBRID, MPPT3, MPPT4, MPPT6, MPPT8, MPPT10, PV

type PvStringFields = tuple[
    RegisterField[float],  # voltage
    RegisterField[float],  # current
    RegisterField[float],  # power
]


class PvStringComponent(SofarComponent):
    """A component serving one or more whole PV strings."""

    strings: ClassVar[Mapping[int, PvStringFields]] = {}


class PvString:
    """One PV string's readings, from the component serving it."""

    def __init__(
        self, number: int, component_name: str, component: PvStringComponent
    ) -> None:
        """Initialize the view."""
        self.number = number
        self.component_name = component_name
        self.component = component
        (
            self._voltage,
            self._current,
            self._power,
        ) = component.strings[number]

    @property
    def voltage(self) -> float | None:
        """The string's voltage, in V."""
        return self._voltage.__get__(self.component)

    @property
    def current(self) -> float | None:
        """The string's current, in A."""
        return self._current.__get__(self.component)

    @property
    def power(self) -> float | None:
        """The string's power, in kW."""
        return self._power.__get__(self.component)


class PvStrings1To2(PvStringComponent):
    """The two PV strings every inverter has, plus total PV power."""

    applies_to = GEN | PV | HYBRID

    pv_voltage_1 = gauge(0x0584, 0.1, signed=False, unit="V")
    pv_current_1 = gauge(0x0585, 0.01, signed=False, unit="A")
    pv_power_1 = gauge(0x0586, 0.01, signed=False, unit="kW")
    pv_voltage_2 = gauge(0x0587, 0.1, signed=False, unit="V")
    pv_current_2 = gauge(0x0588, 0.01, signed=False, unit="A")
    pv_power_2 = gauge(0x0589, 0.01, signed=False, unit="kW")
    pv_power_total = gauge(0x05C4, 0.1, signed=False, unit="kW")

    strings = {
        1: (pv_voltage_1, pv_current_1, pv_power_1),
        2: (pv_voltage_2, pv_current_2, pv_power_2),
    }


class PvString3(PvStringComponent):
    """PV string 3, on inverters with three or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT3 | MPPT4 | MPPT6 | MPPT8 | MPPT10

    pv_voltage_3 = gauge(0x058A, 0.1, signed=False, unit="V")
    pv_current_3 = gauge(0x058B, 0.01, signed=False, unit="A")
    pv_power_3 = gauge(0x058C, 0.01, signed=False, unit="kW")

    strings = {
        3: (pv_voltage_3, pv_current_3, pv_power_3),
    }


class PvString4(PvStringComponent):
    """PV string 4, on inverters with four or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT4 | MPPT6 | MPPT8 | MPPT10

    pv_voltage_4 = gauge(0x058D, 0.1, signed=False, unit="V")
    pv_current_4 = gauge(0x058E, 0.01, signed=False, unit="A")
    pv_power_4 = gauge(0x058F, 0.01, signed=False, unit="kW")

    strings = {
        4: (pv_voltage_4, pv_current_4, pv_power_4),
    }


class PvStrings5To6(PvStringComponent):
    """PV strings 5 and 6, on inverters with six or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT6 | MPPT8 | MPPT10

    pv_voltage_5 = gauge(0x0590, 0.1, signed=False, unit="V")
    pv_current_5 = gauge(0x0591, 0.01, signed=False, unit="A")
    pv_power_5 = gauge(0x0592, 0.01, signed=False, unit="kW")
    pv_voltage_6 = gauge(0x0593, 0.1, signed=False, unit="V")
    pv_current_6 = gauge(0x0594, 0.01, signed=False, unit="A")
    pv_power_6 = gauge(0x0595, 0.01, signed=False, unit="kW")

    strings = {
        5: (pv_voltage_5, pv_current_5, pv_power_5),
        6: (pv_voltage_6, pv_current_6, pv_power_6),
    }


class PvStrings7To8(PvStringComponent):
    """PV strings 7 and 8, on inverters with eight or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT8 | MPPT10

    pv_voltage_7 = gauge(0x0596, 0.1, signed=False, unit="V")
    pv_current_7 = gauge(0x0597, 0.01, signed=False, unit="A")
    pv_power_7 = gauge(0x0598, 0.01, signed=False, unit="kW")
    pv_voltage_8 = gauge(0x0599, 0.1, signed=False, unit="V")
    pv_current_8 = gauge(0x059A, 0.01, signed=False, unit="A")
    pv_power_8 = gauge(0x059B, 0.01, signed=False, unit="kW")

    strings = {
        7: (pv_voltage_7, pv_current_7, pv_power_7),
        8: (pv_voltage_8, pv_current_8, pv_power_8),
    }


class PvStrings9To10(PvStringComponent):
    """PV strings 9 and 10, on ten-MPPT inverters."""

    applies_to = GEN | PV | HYBRID | MPPT10

    pv_voltage_9 = gauge(0x059C, 0.1, signed=False, unit="V")
    pv_current_9 = gauge(0x059D, 0.01, signed=False, unit="A")
    pv_power_9 = gauge(0x059E, 0.01, signed=False, unit="kW")
    pv_voltage_10 = gauge(0x059F, 0.1, signed=False, unit="V")
    pv_current_10 = gauge(0x05A0, 0.01, signed=False, unit="A")
    pv_power_10 = gauge(0x05A1, 0.01, signed=False, unit="kW")

    strings = {
        9: (pv_voltage_9, pv_current_9, pv_power_9),
        10: (pv_voltage_10, pv_current_10, pv_power_10),
    }
