"""Off-grid (EPS) output — the 0x0500 register block, read only when EPS is on."""

from __future__ import annotations

from modbus_connection.model import gauge

from ..model import SofarComponent
from ..variants import EPS, HYBRID, X1, X3


class OffGridTotals(SofarComponent):
    """Off-grid (EPS) totals across all phases."""

    applies_to = HYBRID | EPS

    active_power_offgrid_total = gauge(0x0504, 0.01, signed=True, unit="kW")
    reactive_power_offgrid_total = gauge(0x0505, 0.01, signed=True, unit="kvar")
    apparent_power_offgrid_total = gauge(0x0506, 0.01, signed=True, unit="kVA")
    offgrid_frequency = gauge(0x0507, 0.01, signed=False, unit="Hz")


class OffGridSinglePhase(SofarComponent):
    """Off-grid (EPS) output of a single-phase hybrid inverter."""

    applies_to = X1 | HYBRID | EPS

    offgrid_voltage = gauge(0x050A, 0.1, signed=False, unit="V")
    offgrid_current_output = gauge(0x050B, 0.01, signed=True, unit="A")
    offgrid_active_power_output = gauge(0x050C, 0.01, signed=True, unit="kW")
    offgrid_reactive_power_output = gauge(0x050D, 0.01, signed=True, unit="kvar")
    offgrid_apparent_power_output = gauge(0x050E, 0.01, signed=True, unit="kVA")
    offgrid_load_peak_ratio = gauge(0x050F, 0.01, signed=False)


class OffGridThreePhase(SofarComponent):
    """Off-grid (EPS) per-phase output of a three-phase hybrid inverter."""

    applies_to = X3 | HYBRID | EPS

    offgrid_voltage_l1 = gauge(0x050A, 0.1, signed=False, unit="V")
    offgrid_current_output_l1 = gauge(0x050B, 0.01, signed=True, unit="A")
    offgrid_active_power_output_l1 = gauge(0x050C, 0.01, signed=True, unit="kW")
    offgrid_reactive_power_output_l1 = gauge(0x050D, 0.01, signed=True, unit="kvar")
    offgrid_apparent_power_output_l1 = gauge(0x050E, 0.01, signed=True, unit="kVA")
    offgrid_load_peak_ratio_l1 = gauge(0x050F, 0.01, signed=False)
    offgrid_voltage_l2 = gauge(0x0512, 0.1, signed=False, unit="V")
    offgrid_current_output_l2 = gauge(0x0513, 0.01, signed=True, unit="A")
    offgrid_active_power_output_l2 = gauge(0x0514, 0.01, signed=True, unit="kW")
    offgrid_reactive_power_output_l2 = gauge(0x0515, 0.01, signed=True, unit="kvar")
    offgrid_apparent_power_output_l2 = gauge(0x0516, 0.01, signed=True, unit="kVA")
    offgrid_load_peak_ratio_l2 = gauge(0x0517, 0.01, signed=False)
    offgrid_voltage_l3 = gauge(0x051A, 0.1, signed=False, unit="V")
    offgrid_current_output_l3 = gauge(0x051B, 0.01, signed=True, unit="A")
    offgrid_active_power_output_l3 = gauge(0x051C, 0.01, signed=True, unit="kW")
    offgrid_reactive_power_output_l3 = gauge(0x051D, 0.01, signed=True, unit="kvar")
    offgrid_apparent_power_output_l3 = gauge(0x051E, 0.01, signed=True, unit="kVA")
    offgrid_load_peak_ratio_l3 = gauge(0x051F, 0.01, signed=False)
    offgrid_voltage_output_l1n = gauge(0x0522, 0.1, signed=False, unit="V")
    offgrid_current_output_l1n = gauge(0x0523, 0.01, signed=True, unit="A")
    offgrid_active_power_output_l1n = gauge(0x0524, 0.01, signed=True, unit="kW")
    offgrid_voltage_output_l2n = gauge(0x0525, 0.1, signed=False, unit="V")
    offgrid_current_output_l2n = gauge(0x0526, 0.01, signed=True, unit="A")
    offgrid_active_power_output_l2n = gauge(0x0527, 0.01, signed=True, unit="kW")
