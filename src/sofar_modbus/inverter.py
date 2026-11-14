"""Inverter state, identity and on-grid output, the 0x0400 block."""

from __future__ import annotations

from datetime import datetime
from enum import IntFlag

from modbus_connection.model import enum, flags, gauge, integer, string, uint32

from .enums import (
    Fault1,
    Fault2,
    Fault3,
    Fault4,
    Fault5,
    Fault6,
    Fault7,
    Fault8,
    Fault9,
    Fault10,
    Fault11,
    Fault12,
    Fault13,
    Fault14,
    Fault15,
    Fault16,
    Fault17,
    Fault18,
    Fault19,
    Fault22,
    Fault23,
    Fault26,
    Fault27,
    Fault28,
    Fault29,
    Fault30,
    SystemState,
)
from .faults import FAULTS_BY_ID, Fault
from .model import SofarComponent
from .variants import HYBRID, PV

# Registers 20, 21, 24 and 25 are reserved with no bits assigned.
_FAULT_ENUMS: tuple[type[IntFlag], ...] = (
    Fault1,
    Fault2,
    Fault3,
    Fault4,
    Fault5,
    Fault6,
    Fault7,
    Fault8,
    Fault9,
    Fault10,
    Fault11,
    Fault12,
    Fault13,
    Fault14,
    Fault15,
    Fault16,
    Fault17,
    Fault18,
    Fault19,
    Fault22,
    Fault23,
    Fault26,
    Fault27,
    Fault28,
    Fault29,
    Fault30,
)


def _fault_for(member_name: str) -> Fault | None:
    """The fault an ``ID001_GRID_OVER_VOLTAGE``-style member stands for."""
    return FAULTS_BY_ID.get(int(member_name.removeprefix("ID").split("_", 1)[0]))


# IntFlag members hash by value, so bits from different registers
# collide as dict keys; the register's enum keys the outer lookup.
_REGISTER_FAULTS: dict[type[IntFlag], dict[int, Fault]] = {
    register: {
        member.value: fault
        for name, member in register.__members__.items()
        if (fault := _fault_for(name)) is not None
    }
    for register in _FAULT_ENUMS
}


class InverterState(SofarComponent):
    """Run state, fault bitmaps, temperatures and lifetime counters."""

    applies_to = PV | HYBRID

    system_state = enum(0x0404, SystemState, signed=False)
    fault_1 = flags(0x0405, Fault1, signed=False)
    fault_2 = flags(0x0406, Fault2, signed=False)
    fault_3 = flags(0x0407, Fault3, signed=False)
    fault_4 = flags(0x0408, Fault4, signed=False)
    fault_5 = flags(0x0409, Fault5, signed=False)
    fault_6 = flags(0x040A, Fault6, signed=False)
    fault_7 = flags(0x040B, Fault7, signed=False)
    fault_8 = flags(0x040C, Fault8, signed=False)
    fault_9 = flags(0x040D, Fault9, signed=False)
    fault_10 = flags(0x040E, Fault10, signed=False)
    fault_11 = flags(0x040F, Fault11, signed=False)
    fault_12 = flags(0x0410, Fault12, signed=False)
    fault_13 = flags(0x0411, Fault13, signed=False)
    fault_14 = flags(0x0412, Fault14, signed=False)
    fault_15 = flags(0x0413, Fault15, signed=False)
    fault_16 = flags(0x0414, Fault16, signed=False)
    fault_17 = flags(0x0415, Fault17, signed=False)
    fault_18 = flags(0x0416, Fault18, signed=False)
    waiting_time = integer(0x0417, signed=True, unit="s")
    inverter_temperature_1 = integer(0x0418, signed=True, unit="°C")
    inverter_temperature_2 = integer(0x0419, signed=True, unit="°C")
    heatsink_temperature_1 = integer(0x041A, signed=True, unit="°C")
    heatsink_temperature_2 = integer(0x041B, signed=True, unit="°C")
    heatsink_temperature_3 = integer(0x041C, signed=True, unit="°C")
    heatsink_temperature_4 = integer(0x041D, signed=True, unit="°C")
    heatsink_temperature_5 = integer(0x041E, signed=True, unit="°C")
    heatsink_temperature_6 = integer(0x041F, signed=True, unit="°C")
    module_temperature_1 = integer(0x0420, signed=True, unit="°C")
    module_temperature_2 = integer(0x0421, signed=True, unit="°C")
    module_temperature_3 = integer(0x0422, signed=True, unit="°C")
    generation_time_today = integer(0x0426, signed=False, unit="min")
    generation_time_total = uint32(0x0427, unit="min")
    service_time_total = uint32(0x0429, unit="min")
    insulation_resistance = integer(0x042B, signed=False, unit="kΩ")
    fault_19 = flags(0x0432, Fault19, signed=False)
    fault_20 = integer(0x0433, signed=False)  # reserved, no bits assigned
    fault_21 = integer(0x0434, signed=False)  # reserved, no bits assigned
    fault_22 = flags(0x0435, Fault22, signed=False)
    fault_23 = flags(0x0436, Fault23, signed=False)
    fault_24 = integer(0x0437, signed=False)  # reserved, no bits assigned
    fault_25 = integer(0x0438, signed=False)  # reserved, no bits assigned
    fault_26 = flags(0x0439, Fault26, signed=False)
    fault_27 = flags(0x043A, Fault27, signed=False)
    fault_28 = flags(0x043B, Fault28, signed=False)
    fault_29 = flags(0x043C, Fault29, signed=False)
    fault_30 = flags(0x043D, Fault30, signed=False)

    @property
    def active_faults(self) -> frozenset[Fault]:
        """Every fault the inverter currently reports."""
        return frozenset(
            fault
            for value in (
                self.fault_1,
                self.fault_2,
                self.fault_3,
                self.fault_4,
                self.fault_5,
                self.fault_6,
                self.fault_7,
                self.fault_8,
                self.fault_9,
                self.fault_10,
                self.fault_11,
                self.fault_12,
                self.fault_13,
                self.fault_14,
                self.fault_15,
                self.fault_16,
                self.fault_17,
                self.fault_18,
                self.fault_19,
                self.fault_22,
                self.fault_23,
                self.fault_26,
                self.fault_27,
                self.fault_28,
                self.fault_29,
                self.fault_30,
            )
            if value is not None
            for member in value
            if (fault := _REGISTER_FAULTS[type(value)].get(member.value)) is not None
        )


class Identity(SofarComponent):
    """Serial number, firmware versions and the inverter's real-time clock."""

    applies_to = PV | HYBRID

    _rtc_year = integer(0x042C, signed=False)
    _rtc_month = integer(0x042D, signed=False)
    _rtc_day = integer(0x042E, signed=False)
    _rtc_hour = integer(0x042F, signed=False)
    _rtc_minute = integer(0x0430, signed=False)
    _rtc_second = integer(0x0431, signed=False)
    serial_number = string(0x0445, 7)
    hardware_version = string(0x044D, 2)
    software_version = string(0x044F, 4)

    @property
    def rtc(self) -> datetime | None:
        """The inverter's clock, from the six year-first registers at 0x042C."""
        match (
            self._rtc_year,
            self._rtc_month,
            self._rtc_day,
            self._rtc_hour,
            self._rtc_minute,
            self._rtc_second,
        ):
            case (
                int() as year,
                int() as month,
                int() as day,
                int() as hour,
                int() as minute,
                int() as second,
            ):
                try:
                    return datetime(2000 + year % 100, month, day, hour, minute, second)
                except ValueError:  # an unset clock reports out-of-range parts
                    return None
        return None


class GridOutput(SofarComponent):
    """On-grid output and point-of-common-coupling measurements."""

    applies_to = PV | HYBRID

    grid_frequency = gauge(0x0484, 0.01, signed=False, unit="Hz")
    active_power_output_total = gauge(0x0485, 0.01, signed=True, unit="kW")
    reactive_power_output_total = gauge(0x0486, 0.01, signed=True, unit="kvar")
    apparent_power_output_total = gauge(0x0487, 0.01, signed=True, unit="kVA")
    active_power_pcc_total = gauge(0x0488, 0.01, signed=True, unit="kW")
    reactive_power_pcc_total = gauge(0x0489, 0.01, signed=True, unit="kvar")
    apparent_power_pcc_total = gauge(0x048A, 0.01, signed=True, unit="kVA")
    active_power_pcc_total_wide = gauge(0x048B, 0.1, signed=True, unit="kW")
    """Same reading as active_power_pcc_total, at a scale that won't overflow."""
    voltage_l1 = gauge(0x048D, 0.1, signed=False, unit="V")
    current_output_l1 = gauge(0x048E, 0.01, signed=False, unit="A")
    active_power_output_l1 = gauge(0x048F, 0.01, signed=True, unit="kW")
    reactive_power_output_l1 = gauge(0x0490, 0.01, signed=True, unit="kvar")
    power_factor_output_l1 = gauge(0x0491, 0.001, signed=True)
    current_pcc_l1 = gauge(0x0492, 0.01, signed=False, unit="A")
    active_power_pcc_l1 = gauge(0x0493, 0.01, signed=True, unit="kW")
    reactive_power_pcc_l1 = gauge(0x0494, 0.01, signed=True, unit="kvar")
    power_factor_pcc_l1 = gauge(0x0495, 0.001, signed=True)
    voltage_l2 = gauge(0x0498, 0.1, signed=False, unit="V")
    current_output_l2 = gauge(0x0499, 0.01, signed=False, unit="A")
    active_power_output_l2 = gauge(0x049A, 0.01, signed=True, unit="kW")
    reactive_power_output_l2 = gauge(0x049B, 0.01, signed=True, unit="kvar")
    power_factor_output_l2 = gauge(0x049C, 0.001, signed=True)
    current_pcc_l2 = gauge(0x049D, 0.01, signed=False, unit="A")
    active_power_pcc_l2 = gauge(0x049E, 0.01, signed=True, unit="kW")
    reactive_power_pcc_l2 = gauge(0x049F, 0.01, signed=True, unit="kvar")
    power_factor_pcc_l2 = gauge(0x04A0, 0.001, signed=True)
    voltage_l3 = gauge(0x04A3, 0.1, signed=False, unit="V")
    current_output_l3 = gauge(0x04A4, 0.01, signed=False, unit="A")
    active_power_output_l3 = gauge(0x04A5, 0.01, signed=True, unit="kW")
    reactive_power_output_l3 = gauge(0x04A6, 0.01, signed=True, unit="kvar")
    power_factor_output_l3 = gauge(0x04A7, 0.001, signed=True)
    current_pcc_l3 = gauge(0x04A8, 0.01, signed=False, unit="A")
    active_power_pcc_l3 = gauge(0x04A9, 0.01, signed=True, unit="kW")
    reactive_power_pcc_l3 = gauge(0x04AA, 0.01, signed=True, unit="kvar")
    power_factor_pcc_l3 = gauge(0x04AB, 0.001, signed=True)
    active_power_pv_ext = gauge(0x04AE, 0.01, signed=False, unit="kW")
    active_power_load_sys = gauge(0x04AF, 0.01, signed=False, unit="kW")
    voltage_phase_l1n = gauge(0x04B0, 0.1, signed=False, unit="V")
    current_output_l1n = gauge(0x04B1, 0.01, signed=False, unit="A")
    active_power_output_l1n = gauge(0x04B2, 0.01, signed=True, unit="kW")
    current_pcc_l1n = gauge(0x04B3, 0.01, signed=False, unit="A")
    active_power_pcc_l1n = gauge(0x04B4, 0.01, signed=True, unit="kW")
    voltage_phase_l2n = gauge(0x04B5, 0.1, signed=False, unit="V")
    current_output_l2n = gauge(0x04B6, 0.01, signed=False, unit="A")
    active_power_output_l2n = gauge(0x04B7, 0.01, signed=True, unit="kW")
    current_pcc_l2n = gauge(0x04B8, 0.01, signed=False, unit="A")
    active_power_pcc_l2n = gauge(0x04B9, 0.01, signed=True, unit="kW")
    voltage_line_l1 = gauge(0x04BA, 0.1, signed=False, unit="V")
    voltage_line_l2 = gauge(0x04BB, 0.1, signed=False, unit="V")
    voltage_line_l3 = gauge(0x04BC, 0.1, signed=False, unit="V")
    power_factor_output_total = gauge(0x04BD, 0.001, signed=True)
