"""Which inverter a register belongs to."""

from __future__ import annotations

from enum import IntFlag


class InverterType(IntFlag):
    """The inverter-characterising bitmask, values as upstream defines them."""

    GEN = 0x0001
    """The current-generation register map."""

    X1 = 0x0100
    """Single phase."""
    X3 = 0x0200
    """Three phase."""

    PV = 0x0400
    """PV-only (string) inverter."""
    HYBRID = 0x1000
    """Hybrid PV + battery inverter."""

    EPS = 0x8000
    """Emergency power supply (off-grid output) registers are read."""
    PM = 0x20000
    """Parallel-system (power meter) registers are read."""

    MPPT3 = 0x40000
    MPPT4 = 0x80000
    MPPT6 = 0x100000
    MPPT8 = 0x200000
    MPPT10 = 0x400000

    BAT_BTS = 0x1000000
    """A BTS battery tower; in no group, so the device gates on it."""


GEN = InverterType.GEN
X1 = InverterType.X1
X3 = InverterType.X3
PV = InverterType.PV
HYBRID = InverterType.HYBRID
EPS = InverterType.EPS
PM = InverterType.PM
MPPT3 = InverterType.MPPT3
MPPT4 = InverterType.MPPT4
MPPT6 = InverterType.MPPT6
MPPT8 = InverterType.MPPT8
MPPT10 = InverterType.MPPT10
BAT_BTS = InverterType.BAT_BTS

# Bits OR within a group and AND across groups; a group the mask
# leaves empty matches any inverter, so PV | HYBRID ignores EPS.
_GROUPS = (
    GEN,
    X1 | X3,
    PV | HYBRID,
    EPS,
    PM,
    MPPT3 | MPPT4 | MPPT6 | MPPT8 | MPPT10,
)


def matches(inverter: InverterType, mask: InverterType) -> bool:
    """Whether a component declaring ``mask`` applies to ``inverter``."""
    return all(inverter & mask & group or not mask & group for group in _GROUPS)
