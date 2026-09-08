"""Daily and lifetime energy counters, the 0x0680 register block."""

from __future__ import annotations

from modbus_connection.model import uint32

from ..model import TornReadCorrectedComponent
from ..variants import HYBRID, PV


class EnergyTotals(TornReadCorrectedComponent):
    """Daily and lifetime solar generation."""

    applies_to = PV | HYBRID

    solar_generation_today = uint32(0x0684, scale=0.01, unit="kWh")
    solar_generation_total = uint32(0x0686, scale=0.1, unit="kWh")

    # Duplicated from MeterEnergy so a consumer that still reads them
    # here keeps working. Drop once every consumer has moved over.
    load_consumption_today = uint32(0x0688, scale=0.01, unit="kWh")
    load_consumption_total = uint32(0x068A, scale=0.1, unit="kWh")
    import_energy_today = uint32(0x068C, scale=0.01, unit="kWh")
    import_energy_total = uint32(0x068E, scale=0.1, unit="kWh")
    export_energy_today = uint32(0x0690, scale=0.01, unit="kWh")
    export_energy_total = uint32(0x0692, scale=0.1, unit="kWh")

    _total_increasing_fields = (
        "solar_generation_today",
        "solar_generation_total",
        "load_consumption_today",
        "load_consumption_total",
        "import_energy_today",
        "import_energy_total",
        "export_energy_today",
        "export_energy_total",
    )


# Unmetered models deny this block and read back indeterminate values,
# so the address mask decides whether it is polled at all.
class MeterEnergy(TornReadCorrectedComponent):
    """Daily and lifetime load, import and export energy."""

    applies_to = PV | HYBRID

    load_consumption_today = uint32(0x0688, scale=0.01, unit="kWh")
    load_consumption_total = uint32(0x068A, scale=0.1, unit="kWh")
    import_energy_today = uint32(0x068C, scale=0.01, unit="kWh")
    import_energy_total = uint32(0x068E, scale=0.1, unit="kWh")
    export_energy_today = uint32(0x0690, scale=0.01, unit="kWh")
    export_energy_total = uint32(0x0692, scale=0.1, unit="kWh")

    _total_increasing_fields = (
        "load_consumption_today",
        "load_consumption_total",
        "import_energy_today",
        "import_energy_total",
        "export_energy_today",
        "export_energy_total",
    )


class BatteryEnergy(TornReadCorrectedComponent):
    """Daily and lifetime battery charge and discharge energy."""

    applies_to = HYBRID

    battery_input_energy_today = uint32(0x0694, scale=0.01, unit="kWh")
    battery_input_energy_total = uint32(0x0696, scale=0.1, unit="kWh")
    battery_output_energy_today = uint32(0x0698, scale=0.01, unit="kWh")
    battery_output_energy_total = uint32(0x069A, scale=0.1, unit="kWh")

    _total_increasing_fields = (
        "battery_input_energy_today",
        "battery_input_energy_total",
        "battery_output_energy_today",
        "battery_output_energy_total",
    )
