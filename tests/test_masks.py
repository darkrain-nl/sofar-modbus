"""The AddressMask blocks, decoded over the mock backend."""

from __future__ import annotations

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter
from sofar_modbus.variants import GEN, PV, X1

from .conftest import MODERN_HOLDING

# Captured from a 4.4 KTLX-G3; pins the register order against hardware.
GRID_OUTPUT_MASK = [0x1C00, 0x8218, 0x4308, 0x617F]

# The same unit's energy block: solar generation only, no meter.
UNMETERED_ENERGY_MASK = [0x0000, 0x0000, 0x0000, 0x00FF]
# The meter registers 0x0688-0x0693 declared valid alongside it.
METERED_ENERGY_MASK = [0x0000, 0x0000, 0x000F, 0xFFFF]
# A mask denying even its own four registers, so not a mask at all.
SELF_DENYING_MASK = [0x0000, 0x0000, 0x0000, 0x00F0]

# Every block this library reads registers from, spelled out so a change
# to MASK_BLOCKS has to be made here too.
MODELED_BLOCKS = [
    0x0400,
    0x0440,
    0x0480,
    0x0500,
    0x0580,
    0x05C0,
    0x0600,
    0x0640,
    0x0680,
    0x06C0,
    0x1000,
    0x1040,
    0x1100,
    0x1180,
]
TOWER_BLOCKS = [0x9000, 0x9040]


@pytest.fixture
def pv_inverter(mock_modbus_unit: MockModbusUnit) -> SofarInverter:
    """A PV-only inverter, which has no battery tower to ask about."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    return SofarInverter(mock_modbus_unit, inverter_type=PV | X1)


async def test_a_mask_decodes_most_significant_register_first(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Bit n is base + n, with the block's first register holding the top bits."""
    mock_modbus_unit.holding[0x0480] = GRID_OUTPUT_MASK
    masks = await pv_inverter.async_read_masks()
    assert masks[0x0480] == 0x1C0082184308617F
    assert masks[0x0480] >> (0x0484 - 0x0480) & 1  # grid frequency, served
    assert masks[0x0480] >> (0x0498 - 0x0480) & 1  # voltage L2, served
    assert not masks[0x0480] >> (0x048C - 0x0480) & 1  # unused, not served


async def test_every_modeled_block_is_read(pv_inverter: SofarInverter) -> None:
    """One mask per block holding registers this library decodes."""
    assert sorted(await pv_inverter.async_read_masks()) == MODELED_BLOCKS


async def test_an_unanswered_block_is_left_out(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A model without the block simply has no mask for it."""
    mock_modbus_unit.fail_read(0x0500, IllegalDataAddressError())
    masks = await pv_inverter.async_read_masks()
    assert 0x0500 not in masks
    assert len(masks) == len(MODELED_BLOCKS) - 1


async def test_a_timed_out_block_is_left_out(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Absent blocks time out rather than refusing; that is not a mask either."""
    mock_modbus_unit.fail_read(0x1180, ModbusTimeoutError("no answer"))
    assert 0x1180 not in await pv_inverter.async_read_masks()


async def test_a_dead_link_is_not_read_as_an_absent_mask(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A broken connection has to surface, not read as a model without blocks."""
    mock_modbus_unit.fail_read(0x0600, ModbusConnectionError("link down"))
    with pytest.raises(ModbusConnectionError):
        await pv_inverter.async_read_masks()


async def test_the_tower_blocks_are_skipped_without_a_tower(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Asking a tower-less inverter for the BMS blocks only buys a timeout."""
    await pv_inverter.async_read_masks()
    assert not any(
        event.address in TOWER_BLOCKS for event in mock_modbus_unit.read_events
    )


async def test_the_tower_blocks_are_read_for_a_battery_tower(
    hybrid: SofarInverter,
) -> None:
    """A BTS inverter answers the BMS blocks, so they are worth asking for."""
    assert sorted(await hybrid.async_read_masks()) == MODELED_BLOCKS + TOWER_BLOCKS


async def test_reading_masks_sets_the_inverter_up_first(
    pv_inverter: SofarInverter,
) -> None:
    """Whether a tower exists is only known once setup has run."""
    await pv_inverter.async_read_masks()
    assert pv_inverter.serial_number == "SP1ES12345678"


async def test_a_denied_meter_block_is_not_polled(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """An unmetered model reads indeterminate values there, never zeros."""
    mock_modbus_unit.holding[0x0680] = UNMETERED_ENERGY_MASK
    await pv_inverter.async_update()
    assert "meter_energy" not in pv_inverter.readings_components
    assert "energy" in pv_inverter.readings_components
    assert not any(
        event.address <= 0x0688 < event.address + event.count
        for event in mock_modbus_unit.read_events
    )


async def test_a_served_meter_block_is_polled(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A metered model measures load and import for real, so keep them."""
    mock_modbus_unit.holding[0x0680] = METERED_ENERGY_MASK
    mock_modbus_unit.holding[0x068A] = [0, 500]
    await pv_inverter.async_update()
    assert "meter_energy" in pv_inverter.readings_components
    assert pv_inverter.meter_energy.load_consumption_total == pytest.approx(50.0)


async def test_a_model_publishing_no_mask_keeps_the_meter_block(
    pv_inverter: SofarInverter,
) -> None:
    """Silence decides nothing; only an explicit denial drops a component."""
    await pv_inverter.async_update()
    assert "meter_energy" in pv_inverter.readings_components


async def test_a_self_denying_mask_is_not_trusted(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A real mask always declares its own four registers valid."""
    mock_modbus_unit.holding[0x0680] = SELF_DENYING_MASK
    await pv_inverter.async_update()
    assert "meter_energy" in pv_inverter.readings_components


async def test_an_unanswered_energy_block_keeps_the_meter_block(
    pv_inverter: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A model that refuses the mask has not denied anything."""
    mock_modbus_unit.fail_read(0x0680, IllegalDataAddressError())
    await pv_inverter.async_update()
    assert "meter_energy" in pv_inverter.readings_components


async def test_a_model_without_the_component_is_not_asked(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """No point paying for a mask read to gate what is never polled."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    device = SofarInverter(mock_modbus_unit, inverter_type=GEN | X1)
    await device.async_update()
    assert "meter_energy" not in device.readings_components
    assert not any(event.address == 0x0680 for event in mock_modbus_unit.read_events)
