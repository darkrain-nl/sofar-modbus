"""The older Sofar register map (upstream ``plugin_sofar_old.py``).

Read-only, for SA to SL PV and SE1E/SM1E/ZE1E/ZM1E storage inverters.
"""

from .device import SofarLegacyInverter, identify
from .enums import PvRunMode, StorageRunMode
from .identity import LegacyIdentity
from .pv import HybridPvString1, HybridPvString2, PvCommon, SinglePhasePv, ThreePhasePv
from .storage import AcBatterySettings, Storage, StorageEps, StorageThreePhase

__all__ = [
    "AcBatterySettings",
    "HybridPvString1",
    "HybridPvString2",
    "LegacyIdentity",
    "PvCommon",
    "PvRunMode",
    "SinglePhasePv",
    "SofarLegacyInverter",
    "Storage",
    "StorageEps",
    "StorageRunMode",
    "StorageThreePhase",
    "ThreePhasePv",
    "identify",
]
