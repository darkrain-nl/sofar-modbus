"""Which registers a model actually serves, as the inverter reports it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from modbus_connection import ModbusConnectionError, ModbusError

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


async def async_read_mask(unit: ModbusUnit, base: int) -> int | None:
    """The block's declared-valid mask, or ``None`` if it answers none.

    Bit ``n`` is ``base + n``, most significant register first.
    """
    try:
        registers = await unit.read_holding_registers(base, MASK_REGISTERS)
    except ModbusConnectionError:
        raise  # a dead link is not an absent mask
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
    mask = await async_read_mask(unit, base)
    if mask is None or mask & _SELF_BITS != _SELF_BITS:
        return None
    return bool(mask >> (address - base) & 1)
