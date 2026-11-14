"""Read Sofar Solar inverters over Modbus, as typed Python objects."""

from .model import (
    CorrectedTotal,
    SofarComponent,
    UpdateReport,
)
from .modern import SofarInverter
from .variants import InverterType, matches

__all__ = [
    "CorrectedTotal",
    "InverterType",
    "SofarComponent",
    "SofarInverter",
    "UpdateReport",
    "matches",
]
