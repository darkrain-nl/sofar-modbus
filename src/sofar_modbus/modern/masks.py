"""Which registers a model actually serves, as the inverter reports it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from modbus_connection import (
    ModbusConnectionError,
    ModbusError,
    ModbusTimeoutError,
)

from ..variants import (
    BAT_BTS,
    GEN,
    HYBRID,
    MPPT3,
    MPPT4,
    MPPT6,
    MPPT8,
    MPPT10,
    PV,
    X1,
    X3,
    InverterType,
)

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

MASK_REGISTERS = 4
"""Registers holding the U64 mask that opens each block."""

BLOCK_SIZE = 64
"""Addresses one mask covers."""

# A model that publishes masks always declares its own mask registers.
_SELF_BITS = (1 << MASK_REGISTERS) - 1

# Blocks holding registers this library reads. The spec calls each one
# AddressMask_*; every 64-address block opens with its own.
MASK_BLOCKS: tuple[int, ...] = (
    0x0400,  # state, faults, temperatures, clock
    0x0440,  # serial number and firmware versions
    0x0480,  # on-grid output and PCC
    0x0500,  # off-grid (EPS) output
    0x0580,  # PV strings 1 to 10
    0x05C0,  # total PV power
    0x0600,  # battery strings 1 to 8
    0x0640,  # battery totals
    0x0680,  # energy statistics
    0x06C0,  # nameplate rating
    0x1000,  # clock, feed-in, EPS and parallel settings
    0x1040,  # battery configuration
    0x1100,  # remote control and charger mode
    0x1180,  # passive mode
)

# Components a model can deny outright. One address is enough to ask
# about: the mask that answers covers its whole block.
GATED_COMPONENTS: dict[str, int] = {
    "meter_energy": 0x0688,  # needs a meter at the PCC
}

# Only a battery tower answers these; on anything else they time out.
TOWER_MASK_BLOCKS: tuple[int, ...] = (
    0x9000,  # BMS system information
    0x9040,  # BMS realtime measurements
)

_PHASE_S_VOLTAGE = 0x0498  # served by three-phase models only
_BATTERY_1_VOLTAGE = 0x0604  # served by hybrids only

_PV_STRING_BLOCK = 0x0580
_ALL_BITS = (1 << BLOCK_SIZE) - 1

# PV string voltages, highest first, with the tier polling each. An odd
# string count rounds up to the component reading the pair.
_PV_STRING_TIERS: tuple[tuple[int, InverterType], ...] = (
    (0x059F, MPPT10),
    (0x059C, MPPT10),
    (0x0599, MPPT8),
    (0x0596, MPPT8),
    (0x0593, MPPT6),
    (0x0590, MPPT6),
    (0x058D, MPPT4),
    (0x058A, MPPT3),
)


async def async_read_mask(unit: ModbusUnit, base: int) -> int | None:
    """The block's declared-valid mask, or ``None`` if it answers none.

    Bit ``n`` is ``base + n``, most significant register first.
    """
    try:
        return await _async_read_mask(unit, base)
    except ModbusTimeoutError:
        return None


async def _async_read_mask(unit: ModbusUnit, base: int) -> int | None:
    """The block's mask, or ``None`` if refused; a timeout propagates."""
    try:
        registers = await unit.read_holding_registers(base, MASK_REGISTERS)
    except (ModbusConnectionError, ModbusTimeoutError):
        raise  # a dead or silent link is not an absent mask
    except ModbusError:
        return None
    value = 0
    for register in registers:
        value = value << 16 | register
    return value


async def async_serves(unit: ModbusUnit, address: int) -> bool | None:
    """Whether the model declares ``address`` valid.

    ``None`` when it publishes no usable mask, which decides nothing.
    """
    base = address - address % BLOCK_SIZE
    return _declares(await async_read_mask(unit, base), base, address)


async def async_detect_type(unit: ModbusUnit) -> InverterType | None:
    """The type the model's masks declare, ``None`` if one is unusable."""
    masks: dict[int, int | None] = {}

    async def mask(base: int) -> int | None:
        if base not in masks:
            # A missed answer is no verdict, so it must not settle a type.
            masks[base] = await _async_read_mask(unit, base)
        return masks[base]

    async def serves(address: int) -> bool | None:
        base = address - address % BLOCK_SIZE
        return _declares(await mask(base), base, address)

    if (three_phase := await serves(_PHASE_S_VOLTAGE)) is None:
        return None
    if (hybrid := await serves(_BATTERY_1_VOLTAGE)) is None:
        return None
    if (tier := _pv_tier(await mask(_PV_STRING_BLOCK))) is None:
        return None
    detected = GEN | (X3 if three_phase else X1) | (HYBRID if hybrid else PV)
    detected |= tier
    # A tower's usable mask declares its own base; no tower times out.
    if hybrid and await async_serves(unit, TOWER_MASK_BLOCKS[0]):
        detected |= BAT_BTS
    return detected


async def async_read_pv_tier(unit: ModbusUnit) -> InverterType | None:
    """The PV string tier the model declares, ``None`` if unusable.

    ``InverterType(0)`` means strings 1 and 2 only.
    """
    mask = await async_read_mask(unit, _PV_STRING_BLOCK)
    # Blocks that never answer can still publish an all-ones mask.
    if mask == _ALL_BITS:
        return None
    return _pv_tier(mask)


def _pv_tier(mask: int | None) -> InverterType | None:
    """The tier of the highest PV string ``mask`` declares valid."""
    for address, tier in _PV_STRING_TIERS:
        if (served := _declares(mask, _PV_STRING_BLOCK, address)) is None:
            return None
        if served:
            return tier
    return InverterType(0)


def _declares(mask: int | None, base: int, address: int) -> bool | None:
    """Whether ``mask`` declares ``address`` valid; ``None`` if unusable."""
    if mask is None or mask & _SELF_BITS != _SELF_BITS:
        return None
    return bool(mask >> (address - base) & 1)
