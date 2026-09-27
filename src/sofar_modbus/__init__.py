"""Read Sofar Solar inverters over Modbus, as typed Python objects."""

from .legacy import SofarLegacyInverter
from .model import (
    CorrectedTotal,
    SofarComponent,
    SofarComponentBase,
    SofarLegacyComponent,
    UpdateReport,
)
from .modern import SofarInverter
from .variants import InverterType, matches

__all__ = [
    "CorrectedTotal",
    "InverterType",
    "SofarComponent",
    "SofarComponentBase",
    "SofarInverter",
    "SofarLegacyComponent",
    "SofarLegacyInverter",
    "UpdateReport",
    "matches",
]
