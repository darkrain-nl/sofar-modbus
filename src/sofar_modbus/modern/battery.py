"""Battery strings, the 0x0600 block, one readable block per string."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from modbus_connection.model import RegisterField, gauge, integer

from ..model import SofarComponent
from ..variants import GEN, HYBRID


@dataclass(frozen=True, slots=True)
class BatteryStringFields:
    """The fields one battery string reads from."""

    voltage: RegisterField[float]
    current: RegisterField[float]
    power: RegisterField[float]
    temperature: RegisterField[int]
    capacity: RegisterField[int]
    state_of_health: RegisterField[int]
    charge_cycle: RegisterField[int]


class BatteryStringComponent(SofarComponent):
    """A component serving one or more whole battery strings."""

    strings: ClassVar[Mapping[int, BatteryStringFields]] = {}


class BatteryString:
    """One battery string's readings, from the component serving it."""

    def __init__(self, number: int, component: BatteryStringComponent) -> None:
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
        """The string's current, in A; negative while discharging."""
        return self._fields.current.__get__(self.component)

    @property
    def power(self) -> float | None:
        """The string's power, in kW; negative while discharging."""
        return self._fields.power.__get__(self.component)

    @property
    def temperature(self) -> int | None:
        """The string's temperature, in °C."""
        return self._fields.temperature.__get__(self.component)

    @property
    def capacity(self) -> int | None:
        """The string's state of charge, in %."""
        return self._fields.capacity.__get__(self.component)

    @property
    def state_of_health(self) -> int | None:
        """The string's state of health, in %."""
        return self._fields.state_of_health.__get__(self.component)

    @property
    def charge_cycle(self) -> int | None:
        """The string's charge cycle count."""
        return self._fields.charge_cycle.__get__(self.component)


class BatteryStrings1To2(BatteryStringComponent):
    """Battery strings 1 and 2, each in a readable block of its own."""

    applies_to = HYBRID
    register_ranges = ((0x0604, 0x060A), (0x060B, 0x0611))

    battery_voltage_1 = gauge(0x0604, 0.1, signed=False, unit="V")
    battery_current_1 = gauge(0x0605, 0.01, signed=True, unit="A")
    battery_power_1 = gauge(0x0606, 0.01, signed=True, unit="kW")
    battery_temperature_1 = integer(0x0607, signed=True, unit="°C")
    battery_capacity_1 = integer(0x0608, signed=False, unit="%")
    battery_state_of_health_1 = integer(0x0609, signed=False, unit="%")
    battery_charge_cycle_1 = integer(0x060A, signed=False)
    battery_voltage_2 = gauge(0x060B, 0.1, signed=False, unit="V")
    battery_current_2 = gauge(0x060C, 0.01, signed=True, unit="A")
    battery_power_2 = gauge(0x060D, 0.01, signed=True, unit="kW")
    battery_temperature_2 = integer(0x060E, signed=True, unit="°C")
    battery_capacity_2 = integer(0x060F, signed=False, unit="%")
    battery_state_of_health_2 = integer(0x0610, signed=False, unit="%")
    battery_charge_cycle_2 = integer(0x0611, signed=False)

    strings = {
        1: BatteryStringFields(
            voltage=battery_voltage_1,
            current=battery_current_1,
            power=battery_power_1,
            temperature=battery_temperature_1,
            capacity=battery_capacity_1,
            state_of_health=battery_state_of_health_1,
            charge_cycle=battery_charge_cycle_1,
        ),
        2: BatteryStringFields(
            voltage=battery_voltage_2,
            current=battery_current_2,
            power=battery_power_2,
            temperature=battery_temperature_2,
            capacity=battery_capacity_2,
            state_of_health=battery_state_of_health_2,
            charge_cycle=battery_charge_cycle_2,
        ),
    }


class BatteryStrings3To8(BatteryStringComponent):
    """Battery strings 3 to 8, each in a readable block of its own."""

    applies_to = GEN | HYBRID
    register_ranges = (
        (0x0612, 0x0618),
        (0x0619, 0x061F),
        (0x0620, 0x0626),
        (0x0627, 0x062D),
        (0x062E, 0x0634),
        (0x0635, 0x063B),
    )

    battery_voltage_3 = gauge(0x0612, 0.1, signed=False, unit="V")
    battery_current_3 = gauge(0x0613, 0.01, signed=True, unit="A")
    battery_power_3 = gauge(0x0614, 0.01, signed=True, unit="kW")
    battery_temperature_3 = integer(0x0615, signed=True, unit="°C")
    battery_capacity_3 = integer(0x0616, signed=False, unit="%")
    battery_state_of_health_3 = integer(0x0617, signed=False, unit="%")
    battery_charge_cycle_3 = integer(0x0618, signed=False)
    battery_voltage_4 = gauge(0x0619, 0.1, signed=False, unit="V")
    battery_current_4 = gauge(0x061A, 0.01, signed=True, unit="A")
    battery_power_4 = gauge(0x061B, 0.01, signed=True, unit="kW")
    battery_temperature_4 = integer(0x061C, signed=True, unit="°C")
    battery_capacity_4 = integer(0x061D, signed=False, unit="%")
    battery_state_of_health_4 = integer(0x061E, signed=False, unit="%")
    battery_charge_cycle_4 = integer(0x061F, signed=False)
    battery_voltage_5 = gauge(0x0620, 0.1, signed=False, unit="V")
    battery_current_5 = gauge(0x0621, 0.01, signed=True, unit="A")
    battery_power_5 = gauge(0x0622, 0.01, signed=True, unit="kW")
    battery_temperature_5 = integer(0x0623, signed=True, unit="°C")
    battery_capacity_5 = integer(0x0624, signed=False, unit="%")
    battery_state_of_health_5 = integer(0x0625, signed=False, unit="%")
    battery_charge_cycle_5 = integer(0x0626, signed=False)
    battery_voltage_6 = gauge(0x0627, 0.1, signed=False, unit="V")
    battery_current_6 = gauge(0x0628, 0.01, signed=True, unit="A")
    battery_power_6 = gauge(0x0629, 0.01, signed=True, unit="kW")
    battery_temperature_6 = integer(0x062A, signed=True, unit="°C")
    battery_capacity_6 = integer(0x062B, signed=False, unit="%")
    battery_state_of_health_6 = integer(0x062C, signed=False, unit="%")
    battery_charge_cycle_6 = integer(0x062D, signed=False)
    battery_voltage_7 = gauge(0x062E, 0.1, signed=False, unit="V")
    battery_current_7 = gauge(0x062F, 0.01, signed=True, unit="A")
    battery_power_7 = gauge(0x0630, 0.01, signed=True, unit="kW")
    battery_temperature_7 = integer(0x0631, signed=True, unit="°C")
    battery_capacity_7 = integer(0x0632, signed=False, unit="%")
    battery_state_of_health_7 = integer(0x0633, signed=False, unit="%")
    battery_charge_cycle_7 = integer(0x0634, signed=False)
    battery_voltage_8 = gauge(0x0635, 0.1, signed=False, unit="V")
    battery_current_8 = gauge(0x0636, 0.01, signed=True, unit="A")
    battery_power_8 = gauge(0x0637, 0.01, signed=True, unit="kW")
    battery_temperature_8 = integer(0x0638, signed=True, unit="°C")
    battery_capacity_8 = integer(0x0639, signed=False, unit="%")
    battery_state_of_health_8 = integer(0x063A, signed=False, unit="%")
    battery_charge_cycle_8 = integer(0x063B, signed=False)

    strings = {
        3: BatteryStringFields(
            voltage=battery_voltage_3,
            current=battery_current_3,
            power=battery_power_3,
            temperature=battery_temperature_3,
            capacity=battery_capacity_3,
            state_of_health=battery_state_of_health_3,
            charge_cycle=battery_charge_cycle_3,
        ),
        4: BatteryStringFields(
            voltage=battery_voltage_4,
            current=battery_current_4,
            power=battery_power_4,
            temperature=battery_temperature_4,
            capacity=battery_capacity_4,
            state_of_health=battery_state_of_health_4,
            charge_cycle=battery_charge_cycle_4,
        ),
        5: BatteryStringFields(
            voltage=battery_voltage_5,
            current=battery_current_5,
            power=battery_power_5,
            temperature=battery_temperature_5,
            capacity=battery_capacity_5,
            state_of_health=battery_state_of_health_5,
            charge_cycle=battery_charge_cycle_5,
        ),
        6: BatteryStringFields(
            voltage=battery_voltage_6,
            current=battery_current_6,
            power=battery_power_6,
            temperature=battery_temperature_6,
            capacity=battery_capacity_6,
            state_of_health=battery_state_of_health_6,
            charge_cycle=battery_charge_cycle_6,
        ),
        7: BatteryStringFields(
            voltage=battery_voltage_7,
            current=battery_current_7,
            power=battery_power_7,
            temperature=battery_temperature_7,
            capacity=battery_capacity_7,
            state_of_health=battery_state_of_health_7,
            charge_cycle=battery_charge_cycle_7,
        ),
        8: BatteryStringFields(
            voltage=battery_voltage_8,
            current=battery_current_8,
            power=battery_power_8,
            temperature=battery_temperature_8,
            capacity=battery_capacity_8,
            state_of_health=battery_state_of_health_8,
            charge_cycle=battery_charge_cycle_8,
        ),
    }


class BatteryTotals(SofarComponent):
    """Battery totals across every string."""

    applies_to = HYBRID

    battery_power_total = gauge(0x0667, 0.1, signed=True, unit="kW")
    battery_capacity_total = integer(0x0668, signed=False, unit="%")
    battery_state_of_health_total = integer(0x0669, signed=False, unit="%")
    current_battery_num = integer(0x066A, signed=False)
