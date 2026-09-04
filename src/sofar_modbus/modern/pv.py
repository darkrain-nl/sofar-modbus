"""PV strings — the 0x0580 register block, one component per MPPT tier."""

from __future__ import annotations

from modbus_connection.model import gauge

from ..model import SofarComponent
from ..variants import GEN, HYBRID, MPPT3, MPPT4, MPPT6, MPPT8, MPPT10, PV


class PvStrings1To2(SofarComponent):
    """The two PV strings every inverter has, plus total PV power."""

    applies_to = GEN | PV | HYBRID

    pv_voltage_1 = gauge(0x0584, 0.1, signed=False, unit="V")
    pv_current_1 = gauge(0x0585, 0.01, signed=False, unit="A")
    pv_power_1 = gauge(0x0586, 0.01, signed=False, unit="kW")
    pv_voltage_2 = gauge(0x0587, 0.1, signed=False, unit="V")
    pv_current_2 = gauge(0x0588, 0.01, signed=False, unit="A")
    pv_power_2 = gauge(0x0589, 0.01, signed=False, unit="kW")
    pv_power_total = gauge(0x05C4, 0.1, signed=False, unit="kW")


class PvString3(SofarComponent):
    """PV string 3, on inverters with three or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT3 | MPPT4 | MPPT6 | MPPT8 | MPPT10

    pv_voltage_3 = gauge(0x058A, 0.1, signed=False, unit="V")
    pv_current_3 = gauge(0x058B, 0.01, signed=False, unit="A")
    pv_power_3 = gauge(0x058C, 0.01, signed=False, unit="kW")


class PvString4(SofarComponent):
    """PV string 4, on inverters with four or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT4 | MPPT6 | MPPT8 | MPPT10

    pv_voltage_4 = gauge(0x058D, 0.1, signed=False, unit="V")
    pv_current_4 = gauge(0x058E, 0.01, signed=False, unit="A")
    pv_power_4 = gauge(0x058F, 0.01, signed=False, unit="kW")


class PvStrings5To6(SofarComponent):
    """PV strings 5 and 6, on inverters with six or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT6 | MPPT8 | MPPT10

    pv_voltage_5 = gauge(0x0590, 0.1, signed=False, unit="V")
    pv_current_5 = gauge(0x0591, 0.01, signed=False, unit="A")
    pv_power_5 = gauge(0x0592, 0.01, signed=False, unit="kW")
    pv_voltage_6 = gauge(0x0593, 0.1, signed=False, unit="V")
    pv_current_6 = gauge(0x0594, 0.01, signed=False, unit="A")
    pv_power_6 = gauge(0x0595, 0.01, signed=False, unit="kW")


class PvStrings7To8(SofarComponent):
    """PV strings 7 and 8, on inverters with eight or more MPPTs."""

    applies_to = GEN | PV | HYBRID | MPPT8 | MPPT10

    pv_voltage_7 = gauge(0x0596, 0.1, signed=False, unit="V")
    pv_current_7 = gauge(0x0597, 0.01, signed=False, unit="A")
    pv_power_7 = gauge(0x0598, 0.01, signed=False, unit="kW")
    pv_voltage_8 = gauge(0x0599, 0.1, signed=False, unit="V")
    pv_current_8 = gauge(0x059A, 0.01, signed=False, unit="A")
    pv_power_8 = gauge(0x059B, 0.01, signed=False, unit="kW")


class PvStrings9To10(SofarComponent):
    """PV strings 9 and 10, on ten-MPPT inverters."""

    applies_to = GEN | PV | HYBRID | MPPT10

    pv_voltage_9 = gauge(0x059C, 0.1, signed=False, unit="V")
    pv_current_9 = gauge(0x059D, 0.01, signed=False, unit="A")
    pv_power_9 = gauge(0x059E, 0.01, signed=False, unit="kW")
    pv_voltage_10 = gauge(0x059F, 0.1, signed=False, unit="V")
    pv_current_10 = gauge(0x05A0, 0.01, signed=False, unit="A")
    pv_power_10 = gauge(0x05A1, 0.01, signed=False, unit="kW")
