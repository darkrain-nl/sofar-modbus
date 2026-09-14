"""Read Sofar Solar inverters over Modbus, as typed Python objects."""

from .legacy import SofarLegacyInverter
from .model import (
    SofarComponent,
    SofarComponentBase,
    SofarLegacyComponent,
    UpdateReport,
)
from .modern import SofarInverter
from .variants import InverterType, matches

__all__ = [
    "InverterType",
    "SofarComponent",
    "SofarComponentBase",
    "SofarInverter",
    "SofarLegacyComponent",
    "SofarLegacyInverter",
    "UpdateReport",
    "matches",
]
