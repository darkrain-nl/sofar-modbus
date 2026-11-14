"""PV strings, the 0x0580 register block, one component per MPPT tier."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from modbus_connection.model import RegisterField, gauge

from .model import SofarComponent
from .variants import GEN, HYBRID, MPPT3, MPPT4, MPPT6, MPPT8, MPPT10, PV


@dataclass(frozen=True, slots=True)
class PvStringFields:
    """The fields one PV string reads from."""

    voltage: RegisterField[float]
    current: RegisterField[float]
    power: RegisterField[float]


class PvStringComponent(SofarComponent):
    """A component serving one or more whole PV strings."""

    strings: ClassVar[Mapping[int, PvStringFields]] = {}


class PvString:
    """One PV string's readings, from the component serving it."""

    def __init__(self, number: int, component: PvStringComponent) -> None:
        """Initialize the view."""
        self.number = number
        self.component = component
        self._fields = component.strings[number]

    @property
    def voltage(self) -> float | None:
        """The string's voltage, in V."""
        return self._fields.voltage.__get__(self.component)

    @property
    def current(self) -> float | None:
        """The string's current, in A."""
        return self._fields.current.__get__(self.component)

    @property
    def power(self) -> float | None:
        """The string's power, in kW."""
        return self._fields.power.__get__(self.component)


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
        1: PvStringFields(
            voltage=pv_voltage_1,
            current=pv_current_1,
            power=pv_power_1,
        ),
        2: PvStringFields(
            voltage=pv_voltage_2,
            current=pv_current_2,
            power=pv_power_2,
        ),
    }


class PvString3(PvStringComponent):
    """PV string 3, on inverters with three or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT3 | MPPT4 | MPPT6 | MPPT8 | MPPT10

    pv_voltage_3 = gauge(0x058A, 0.1, signed=False, unit="V")
    pv_current_3 = gauge(0x058B, 0.01, signed=False, unit="A")
    pv_power_3 = gauge(0x058C, 0.01, signed=False, unit="kW")

    strings = {
        3: PvStringFields(
            voltage=pv_voltage_3,
            current=pv_current_3,
            power=pv_power_3,
        ),
    }


class PvString4(PvStringComponent):
    """PV string 4, on inverters with four or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT4 | MPPT6 | MPPT8 | MPPT10

    pv_voltage_4 = gauge(0x058D, 0.1, signed=False, unit="V")
    pv_current_4 = gauge(0x058E, 0.01, signed=False, unit="A")
    pv_power_4 = gauge(0x058F, 0.01, signed=False, unit="kW")

    strings = {
        4: PvStringFields(
            voltage=pv_voltage_4,
            current=pv_current_4,
            power=pv_power_4,
        ),
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
        5: PvStringFields(
            voltage=pv_voltage_5,
            current=pv_current_5,
            power=pv_power_5,
        ),
        6: PvStringFields(
            voltage=pv_voltage_6,
            current=pv_current_6,
            power=pv_power_6,
        ),
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
        7: PvStringFields(
            voltage=pv_voltage_7,
            current=pv_current_7,
            power=pv_power_7,
        ),
        8: PvStringFields(
            voltage=pv_voltage_8,
            current=pv_current_8,
            power=pv_power_8,
        ),
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
        9: PvStringFields(
            voltage=pv_voltage_9,
            current=pv_current_9,
            power=pv_power_9,
        ),
        10: PvStringFields(
            voltage=pv_voltage_10,
            current=pv_current_10,
            power=pv_power_10,
        ),
    }
